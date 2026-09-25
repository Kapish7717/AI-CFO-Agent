"""Tests for the stripe ingestion LangGraph node (Step 3).

Offline: the MCP tool layer is faked, proving the deterministic node sequence
(fetch -> write unified/raw -> mark status) without spawning MCP subprocesses
or touching Stripe/Supabase.
"""

import json

import pytest

from app.graph import ingestion_node as node


class _FakeTool:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return self.result


def _json_tool(name, payload):
    return _FakeTool(name, json.dumps(payload))


def _envelope(payload):
    """The shape langchain-mcp-adapters really returns: MCP content blocks."""
    return [{"type": "text", "text": json.dumps(payload), "id": "lc_1"}]


def _envelope_tool(name, payload):
    return _FakeTool(name, _envelope(payload))


def _make_tools(**overrides):
    charge = {"object": "charge", "id": "ch_1", "amount": 5000}
    refund = {"object": "refund", "id": "re_1", "amount": 1250}
    sub = {"object": "subscription", "id": "sub_1", "status": "active"}
    transfer = {"object": "transfer", "id": "tr_1", "amount": 2000}
    payout = {"object": "payout", "id": "po_1", "amount": 3000}

    defaults = {
        "fetch_charges": [charge],
        "fetch_refunds": [refund],
        "fetch_subscriptions": [sub],
        "fetch_transfers": [transfer],
        "fetch_payouts": [payout],
        "write_transactions": {"inserted": 4},
        "write_stripe_transactions": {"inserted": 5},
        "mark_sync_status": {"source": "stripe", "status": "healthy"},
    }
    defaults.update(overrides)

    tools = [_json_tool(name, payload) for name, payload in defaults.items()]
    return {t.name: t for t in tools}, tools


def _patch_tools(monkeypatch, tools):
    async def fake_get_pipeline_tools():
        return tools

    monkeypatch.setattr(node, "get_pipeline_tools", fake_get_pipeline_tools)


def _make_envelope_tools(**overrides):
    """Same payloads as _make_tools, but wrapped in real MCP content blocks."""
    charge = {"object": "charge", "id": "ch_1", "amount": 5000}
    refund = {"object": "refund", "id": "re_1", "amount": 1250}
    sub = {"object": "subscription", "id": "sub_1", "status": "active"}
    transfer = {"object": "transfer", "id": "tr_1", "amount": 2000}
    payout = {"object": "payout", "id": "po_1", "amount": 3000}

    defaults = {
        "fetch_charges": [charge],
        "fetch_refunds": [refund],
        "fetch_subscriptions": [sub],
        "fetch_transfers": [transfer],
        "fetch_payouts": [payout],
        "write_transactions": {"inserted": 4},
        "write_stripe_transactions": {"inserted": 5},
        "mark_sync_status": {"source": "stripe", "status": "healthy"},
    }
    defaults.update(overrides)

    tools = [_envelope_tool(name, payload) for name, payload in defaults.items()]
    return {t.name: t for t in tools}, tools


def test_as_records_unwraps_mcp_content_envelope():
    """A text envelope must decode to the record, not become the record."""
    envelope = [{"type": "text", "text": json.dumps([{"id": "ch_1", "amount": 5000}])}]

    assert node._as_records(envelope) == [{"id": "ch_1", "amount": 5000}]


def test_as_records_surfaces_enveloped_error():
    """An error inside an envelope must stay an error, never become a record."""
    envelope = [{"type": "text", "text": json.dumps({"error": "No module named 'stripe'"})}]

    records = node._as_records(envelope)

    assert records == [{"error": "No module named 'stripe'"}]
    assert "error" in records[0]


def test_as_records_joins_multiple_text_frames():
    envelope = [
        {"type": "text", "text": json.dumps([{"id": "ch_1"}])},
        {"type": "text", "text": json.dumps([{"id": "ch_2"}])},
    ]

    assert node._as_records(envelope) == [{"id": "ch_1"}, {"id": "ch_2"}]


def test_as_records_leaves_plain_records_untouched():
    assert node._as_records([{"id": "ch_1"}]) == [{"id": "ch_1"}]


@pytest.mark.anyio
async def test_node_handles_real_mcp_envelope(monkeypatch):
    """Full node against envelope-shaped tools, as production actually returns."""
    by_name, tools = _make_envelope_tools()
    _patch_tools(monkeypatch, tools)

    out = await node.stripe_ingestion_node({"user_id": 7})

    assert out["sync_result"]["success"] is True
    assert out["sync_result"]["record_count"] == 4
    assert out["sync_result"]["fetched"] == {
        "fetch_charges": 1,
        "fetch_refunds": 1,
        "fetch_subscriptions": 1,
        "fetch_transfers": 1,
        "fetch_payouts": 1,
    }
    unified_ids = [r["id"] for r in by_name["write_transactions"].calls[0]["transactions"]]
    assert unified_ids == ["ch_1", "re_1", "tr_1", "po_1"]


@pytest.mark.anyio
async def test_node_fails_loudly_on_enveloped_fetch_error(monkeypatch):
    """The regression that let a dead stripe import report success."""
    by_name, tools = _make_envelope_tools(fetch_charges={"error": "No module named 'stripe'"})
    _patch_tools(monkeypatch, tools)

    out = await node.stripe_ingestion_node({"user_id": 7})

    assert out["sync_result"]["success"] is False
    assert out["sync_result"]["fetched"]["fetch_charges"] == 0
    assert "No module named" in out["sync_result"]["errors"]["fetch_charges"]
    assert by_name["mark_sync_status"].calls[0]["status"] == "error"


@pytest.mark.anyio
async def test_node_happy_path(monkeypatch):
    by_name, tools = _make_tools()
    _patch_tools(monkeypatch, tools)

    out = await node.stripe_ingestion_node({"user_id": 7})

    assert out["sync_result"]["success"] is True
    assert out["source"] == "stripe"
    assert out["sync_result"]["record_count"] == 4
    assert out["sync_result"]["fetched"] == {
        "fetch_charges": 1,
        "fetch_refunds": 1,
        "fetch_subscriptions": 1,
        "fetch_transfers": 1,
        "fetch_payouts": 1,
    }

    # unified write: charges + refunds + transfers + payouts (NO subscriptions)
    unified_args = by_name["write_transactions"].calls[0]
    assert unified_args["source"] == "stripe"
    assert unified_args["user_id"] == 7
    unified_ids = [r["id"] for r in unified_args["transactions"]]
    assert unified_ids == ["ch_1", "re_1", "tr_1", "po_1"]

    # raw write: everything including subscriptions
    raw_ids = [r["id"] for r in by_name["write_stripe_transactions"].calls[0]["records"]]
    assert raw_ids == ["ch_1", "re_1", "sub_1", "tr_1", "po_1"]

    # sync status: healthy with inserted count
    status_args = by_name["mark_sync_status"].calls[0]
    assert status_args["status"] == "healthy"
    assert status_args["record_count"] == 4


@pytest.mark.anyio
async def test_node_handles_fetch_error(monkeypatch):
    by_name, tools = _make_tools(fetch_charges={"error": "stripe: invalid key"})
    _patch_tools(monkeypatch, tools)

    out = await node.stripe_ingestion_node({"user_id": 7})

    assert out["sync_result"]["success"] is False
    assert out["sync_result"]["fetched"]["fetch_charges"] == 0
    assert "fetch_charges" in out["sync_result"]["errors"]

    # subscriptions still land in the raw mirror even when charges failed
    raw_ids = [r["id"] for r in by_name["write_stripe_transactions"].calls[0]["records"]]
    assert "sub_1" in raw_ids
    assert by_name["mark_sync_status"].calls[0]["status"] == "error"


@pytest.mark.anyio
async def test_node_requires_user_id(monkeypatch):
    _, tools = _make_tools()
    _patch_tools(monkeypatch, tools)

    out = await node.stripe_ingestion_node({})

    assert out["sync_result"]["success"] is False
    assert "user_id" in out["sync_result"]["error"]


@pytest.mark.anyio
async def test_node_reports_missing_write_tool(monkeypatch):
    _, tools = _make_tools()
    tools = [t for t in tools if t.name != "write_transactions"]
    _patch_tools(monkeypatch, tools)

    out = await node.stripe_ingestion_node({"user_id": 7})

    assert out["sync_result"]["success"] is False
    assert "unified" in out["sync_result"]["errors"]


@pytest.mark.anyio
async def test_pipeline_graph_compiles_and_runs_with_mocked_node(monkeypatch):
    """Compile the real graph; prove state flows START -> stripe_ingest -> END
    by stubbing the single node."""
    import app.graph.pipeline as pipeline

    async def stub_node(state):
        return {
            "source": "stripe",
            "sync_result": {"success": True, "record_count": 7, "fetched": {}, "errors": None},
        }

    monkeypatch.setattr(pipeline, "stripe_ingestion_node", stub_node)
    builder = pipeline.build_graph()
    result = await builder.ainvoke(
        {"user_id": 1, "trigger": "new_data", "fetch_limit": 25}, {"recursion_limit": 5}
    )
    assert result["source"] == "stripe"
    assert result["sync_result"]["success"] is True


@pytest.mark.anyio
async def test_stripe_server_registers_expected_tools():
    from app.mcp.stripe.server import mcp

    tools = await mcp.list_tools()
    assert {t.name for t in tools} == {
        "fetch_charges",
        "fetch_refunds",
        "fetch_subscriptions",
        "fetch_transfers",
        "fetch_payouts",
    }