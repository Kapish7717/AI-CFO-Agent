"""Tests for the shared MCP tool plumbing (app/graph/mcp_tools.py).

Offline: fake tools only. These cover the contract every node depends on --
results come back as list[dict], failures arrive as a record carrying "error"
rather than an exception, and a wedged tool is bounded instead of hanging.
"""

import asyncio
import json
import logging

import pytest

from app.graph import mcp_tools as tools_mod


class _FakeTool:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return self.result


class _HangingTool:
    """A tool that never returns, standing in for a wedged MCP subprocess."""

    def __init__(self, name):
        self.name = name
        self.cancelled = False

    async def ainvoke(self, args):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _envelope(payload):
    """The shape langchain-mcp-adapters really returns: MCP content blocks."""
    return [{"type": "text", "text": json.dumps(payload), "id": "lc_1"}]


# --- normalization --------------------------------------------------------


def test_as_records_unwraps_mcp_content_envelope():
    """A text envelope must decode to the record, not become the record."""
    envelope = _envelope([{"id": "ch_1", "amount": 5000}])

    assert tools_mod._as_records(envelope) == [{"id": "ch_1", "amount": 5000}]


def test_as_records_surfaces_enveloped_error():
    """An error inside an envelope must stay an error, never become a record."""
    envelope = _envelope({"error": "No module named 'stripe'"})

    records = tools_mod._as_records(envelope)

    assert records == [{"error": "No module named 'stripe'"}]
    assert "error" in records[0]


def test_as_records_joins_multiple_text_frames():
    envelope = [
        {"type": "text", "text": json.dumps([{"id": "ch_1"}])},
        {"type": "text", "text": json.dumps([{"id": "ch_2"}])},
    ]

    assert tools_mod._as_records(envelope) == [{"id": "ch_1"}, {"id": "ch_2"}]


def test_as_records_leaves_plain_records_untouched():
    assert tools_mod._as_records([{"id": "ch_1"}]) == [{"id": "ch_1"}]


def test_as_records_accepts_bare_json_string():
    """Fakes return a plain string; production returns blocks. Both must work."""
    assert tools_mod._as_records(json.dumps([{"id": "ch_1"}])) == [{"id": "ch_1"}]


def test_as_records_flags_unparseable_payload():
    records = tools_mod._as_records("not json at all")

    assert "unparseable tool result" in records[0]["error"]


def test_ok_records_drops_failures():
    records = [{"id": "ch_1"}, {"error": "boom"}, {"id": "ch_2"}]

    assert tools_mod._ok_records(records) == [{"id": "ch_1"}, {"id": "ch_2"}]


# --- invocation -----------------------------------------------------------


@pytest.mark.anyio
async def test_call_returns_normalized_records():
    tool = _FakeTool("fetch_charges", _envelope([{"id": "ch_1"}]))

    records = await tools_mod._call([tool], "fetch_charges", user_id=4, limit=10)

    assert records == [{"id": "ch_1"}]
    assert tool.calls == [{"user_id": 4, "limit": 10}]


@pytest.mark.anyio
async def test_call_reports_missing_tool_without_raising():
    records = await tools_mod._call([], "fetch_charges", user_id=4)

    assert records == [{"error": "MCP tool 'fetch_charges' unavailable"}]


@pytest.mark.anyio
async def test_call_converts_exception_to_error_record():
    class _Boom:
        name = "fetch_charges"

        async def ainvoke(self, args):
            raise RuntimeError("subprocess died")

    records = await tools_mod._call([_Boom()], "fetch_charges", user_id=4)

    assert "call to 'fetch_charges' failed" in records[0]["error"]
    assert "subprocess died" in records[0]["error"]


# --- timeouts -------------------------------------------------------------
# The stdio transport has no timeout of its own, so without one in _call a
# wedged MCP subprocess hangs the whole graph at 0% CPU with nothing to show.


@pytest.mark.anyio
async def test_call_times_out_instead_of_hanging():
    tool = _HangingTool("fetch_charges")

    out = await tools_mod._call([tool], "fetch_charges", user_id=1, timeout=0.05)

    assert len(out) == 1
    assert "timed out" in out[0]["error"]
    assert "0.05" in out[0]["error"]
    assert tool.cancelled is True, "the abandoned coroutine must be cancelled, not leaked"


def test_timeout_defaults_per_tool(monkeypatch):
    monkeypatch.delenv("MCP_CALL_TIMEOUT", raising=False)

    assert tools_mod._timeout_for("fetch_charges") == 120.0
    assert tools_mod._timeout_for("generate_cfo_pdf_report") == 300.0


def test_timeout_env_override(monkeypatch):
    monkeypatch.setenv("MCP_CALL_TIMEOUT", "5")

    assert tools_mod._timeout_for("generate_cfo_pdf_report") == 5.0


def test_timeout_ignores_unparseable_override(monkeypatch):
    monkeypatch.setenv("MCP_CALL_TIMEOUT", "soon")

    assert tools_mod._timeout_for("fetch_charges") == 120.0


# --- timing ----------------------------------------------------------------
# A failure comes back as an ordinary record, so nothing downstream can tell a
# 120s timeout from a fast success by inspecting the return value. The timing
# line is the only place that distinction is recorded, so it has to be emitted on
# every outcome, not just the successful one.


@pytest.mark.anyio
async def test_call_logs_ok_with_duration_and_record_count(caplog):
    tool = _FakeTool("fetch_charges", _envelope([{"id": "ch_1"}, {"id": "ch_2"}]))

    with caplog.at_level(logging.INFO, logger=tools_mod.logger.name):
        await tools_mod._call([tool], "fetch_charges", user_id=4, limit=10)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.INFO
    assert "fetch_charges" in record.getMessage()
    assert "ok" in record.getMessage()
    assert "records=2" in record.getMessage()
    assert "ms" in record.getMessage()


@pytest.mark.anyio
async def test_call_logs_timeout_with_the_limit_it_hit(caplog):
    tool = _HangingTool("fetch_charges")

    with caplog.at_level(logging.INFO, logger=tools_mod.logger.name):
        await tools_mod._call([tool], "fetch_charges", user_id=1, timeout=0.05)

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "timeout" in message
    assert "limit=0.05s" in message
    assert caplog.records[0].levelno == logging.WARNING


@pytest.mark.anyio
async def test_call_logs_failure_and_truncates_a_huge_error(caplog):
    class _Boom:
        name = "fetch_charges"

        async def ainvoke(self, args):
            raise RuntimeError("x" * 5000)

    with caplog.at_level(logging.INFO, logger=tools_mod.logger.name):
        records = await tools_mod._call([_Boom()], "fetch_charges", user_id=4)

    assert "call to 'fetch_charges' failed" in records[0]["error"]
    message = caplog.records[0].getMessage()
    assert "failed" in message
    assert "x" * 200 not in message, "the error must be truncated so one failure cannot flood the log"


@pytest.mark.anyio
async def test_call_logs_missing_tool(caplog):
    with caplog.at_level(logging.INFO, logger=tools_mod.logger.name):
        records = await tools_mod._call([], "fetch_charges", user_id=4)

    assert records == [{"error": "MCP tool 'fetch_charges' unavailable"}]
    assert "missing" in caplog.records[0].getMessage()


@pytest.mark.anyio
async def test_slow_call_is_warned_not_info(caplog, monkeypatch):
    monkeypatch.setattr(tools_mod, "_SLOW_CALL_MS", 0.0)
    tool = _FakeTool("fetch_charges", _envelope([{"id": "ch_1"}]))

    with caplog.at_level(logging.INFO, logger=tools_mod.logger.name):
        await tools_mod._call([tool], "fetch_charges", user_id=4)

    assert caplog.records[0].levelno == logging.WARNING


@pytest.mark.anyio
async def test_broken_logger_cannot_break_a_successful_call(monkeypatch):
    """A stopwatch that fails the run it is measuring is worse than no stopwatch."""

    def _explode(*args, **kwargs):
        raise RuntimeError("logging is down")

    monkeypatch.setattr(tools_mod.logger, "log", _explode)
    tool = _FakeTool("fetch_charges", _envelope([{"id": "ch_1"}]))

    records = await tools_mod._call([tool], "fetch_charges", user_id=4)

    assert records == [{"id": "ch_1"}]
