# ==========================================================
# Shared MCP tool plumbing for the graph nodes
# ==========================================================
# The ingestion, anomaly and reporting nodes all call MCP tools, and all of them
# need the same four things: look the tool up in the flat tool list, invoke it
# under a deadline, time it, and turn whatever comes back into a predictable
# shape. That lives here rather than in any one node, so no node has to import
# another node's internals.
#
# Two conventions the nodes rely on:
#   * results are always list[dict];
#   * a failure is a record carrying "error", never an exception, so a missing
#     tool, a failed call and a timeout all degrade one step instead of the run.
#
# Because failures are data rather than exceptions, the timing line emitted here
# is the only place the run's own logs record that a tool was slow or that it
# timed out at all.

import asyncio
import json
import logging
import os
import time

logger = logging.getLogger("cfo.graph.mcp_tools")

# A wedged MCP subprocess must fail the node, not hang the graph. The stdio
# transport has no timeout of its own, so without this a stuck tool leaves the
# run spinning at 0% CPU with nothing to show and no way to tell which step
# failed. On timeout the node records the error and carries on; the abandoned
# subprocess may still need the process restarted.
_DEFAULT_TIMEOUT = 120.0

# A whole pipeline is allowed minutes, so a call is only worth a WARNING once it
# is big enough to dominate a run. Everything else is INFO and stays out of the way.
_SLOW_CALL_MS = 10_000.0

# Report generation runs a full LLM pass plus a PDF render and a storage upload,
# so it legitimately takes longer than a fetch or a read. Delivery carries a
# base64-encoded PDF upload to Gmail, which needs its own allowance rather than
# inheriting a deadline sized for small reads.
_TOOL_TIMEOUTS = {
    "generate_cfo_pdf_report": 300.0,
    "send_email_report": 180.0,
}


def _is_text_content(item) -> bool:
    return isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)


def _unwrap_envelope(result):
    """Strip the MCP content envelope, i.e. ``[{"type": "text", "text": "<json>"}]``
    becomes the list of text frames it carries.

    langchain-mcp-adapters hands back raw MCP content blocks. Without unwrapping,
    the envelope is indistinguishable from a one-record result, so real payloads
    are silently dropped and error payloads are mistaken for valid records.
    """
    if isinstance(result, list) and result and all(_is_text_content(item) for item in result):
        return [item["text"] for item in result]
    return result


def _decode(text: str):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return {"error": f"unparseable tool result: {str(text)[:200]}"}


def _as_records(result) -> list[dict]:
    """Normalize an MCP tool result (content envelope / JSON text) into records."""
    payload = _unwrap_envelope(result)
    if isinstance(payload, list) and payload and all(isinstance(frame, str) for frame in payload):
        # Several text frames: decode each separately, then flatten. Concatenating
        # them would produce invalid JSON whenever a tool returns more than one.
        records: list[dict] = []
        for frame in payload:
            records.extend(_as_records(frame))
        return records
    parsed = _decode(payload) if isinstance(payload, str) else payload
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return parsed
    return [{"error": f"unexpected tool result type: {type(parsed).__name__}"}]


def _ok_records(records: list[dict]) -> list[dict]:
    return [r for r in records if isinstance(r, dict) and "error" not in r]


def _find_tool(tools, name):
    return next((t for t in tools if getattr(t, "name", None) == name), None)


def _timeout_for(name: str) -> float:
    """Resolve the timeout for a tool call: env override, then per-tool, then default."""
    override = os.getenv("MCP_CALL_TIMEOUT", "").strip()
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    return _TOOL_TIMEOUTS.get(name, _DEFAULT_TIMEOUT)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _log_call(name: str, outcome: str, elapsed_ms: float, *, limit=None, err=None, records=None) -> None:
    """Emit one timing line per tool call: how long it took and how it ended.

    Failures arrive as ordinary records rather than exceptions, so nothing
    downstream can tell a 120s timeout from a fast success by looking at the
    return value. This is where that distinction is preserved.

    Logging must never be able to fail a call that would otherwise have
    succeeded, so every error here is swallowed: a stopwatch that breaks the run
    it is measuring is worse than no stopwatch.
    """
    detail = ""
    if limit is not None:
        detail = f" limit={limit:g}s"
    elif records is not None:
        detail = f" records={records}"
    if err is not None:
        detail = f" err={str(err)[:120]}"
    slow = elapsed_ms >= _SLOW_CALL_MS
    level = logging.INFO if outcome == "ok" and not slow else logging.WARNING
    try:
        logger.log(level, "MCP tool %s %s %.0fms%s", name, outcome, elapsed_ms, detail)
    except Exception:
        pass


async def _call(tools, name: str, user_id: int, timeout: float | None = None, **kwargs) -> list[dict]:
    """Invoke an MCP tool and normalize the result, never raising.

    ``tools`` is the flat list from ``get_pipeline_tools()``; the caller does not
    need to know which server owns the tool, only its name. A missing tool, a
    failed call and a timeout all come back as a single record carrying
    ``error``, which is the shape every node already checks for, so one stuck
    tool degrades its stage instead of taking down the run.

    Every call is timed and logged on the way out, on all four outcomes
    (missing, ok, timeout, failed).
    """
    tool = _find_tool(tools, name)
    if tool is None:
        _log_call(name, "missing", 0.0)
        return [{"error": f"MCP tool '{name}' unavailable"}]
    limit = _timeout_for(name) if timeout is None else timeout
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            tool.ainvoke({"user_id": user_id, **kwargs}), timeout=limit
        )
        records = _as_records(result)
    except asyncio.TimeoutError:
        _log_call(name, "timeout", _elapsed_ms(started), limit=limit)
        return [{"error": f"call to '{name}' timed out after {limit:g}s"}]
    except Exception as e:
        _log_call(name, "failed", _elapsed_ms(started), err=e)
        return [{"error": f"call to '{name}' failed: {e}"}]
    _log_call(name, "ok", _elapsed_ms(started), records=len(records))
    return records
