# ==========================================================
# Ingestion node: stripe-mcp -> supabase-mcp
# ==========================================================

import json

from app.graph.mcp_client import get_pipeline_tools
from app.graph.state import PipelineState

STRIPE = "stripe"

# All stripe-mcp fetch tools the node calls. Subscriptions are fetched but NOT
# written to unified_transactions (they are future obligations, not cash-flow
# rows); they land only in the raw stripe_transactions mirror.
_FETCH_TOOLS = (
    "fetch_charges",
    "fetch_refunds",
    "fetch_subscriptions",
    "fetch_transfers",
    "fetch_payouts",
)
_UNIFIED_SOURCES = (
    "fetch_charges",
    "fetch_refunds",
    "fetch_transfers",
    "fetch_payouts",
)


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


async def _call(tools, name: str, user_id: int, **kwargs) -> list[dict]:
    tool = _find_tool(tools, name)
    if tool is None:
        return [{"error": f"MCP tool '{name}' unavailable"}]
    try:
        result = await tool.ainvoke({"user_id": user_id, **kwargs})
        return _as_records(result)
    except Exception as e:
        return [{"error": f"call to '{name}' failed: {e}"}]


async def stripe_ingestion_node(state: PipelineState) -> dict:
    """Fetch Stripe objects via stripe-mcp and persist them via supabase-mcp.

    Deterministic (no LLM): every call is a fixed sequence of bound MCP tools.
    State flow:  user_id + fetch_limit in  -> sync_result out (source/record
    counts/errors). Writes are idempotent on (external_id, source, user_id).
    """
    user_id = state.get("user_id")
    if not user_id:
        return {"sync_result": {"success": False, "error": "state['user_id'] is required"}}

    limit = state.get("fetch_limit", 100)
    tools = await get_pipeline_tools()

    fetched: dict[str, list[dict]] = {}
    fetch_errors: dict[str, str] = {}
    for name in _FETCH_TOOLS:
        records = await _call(tools, name, user_id=user_id, limit=limit)
        err = next((r["error"] for r in records if "error" in r), None)
        if err:
            fetch_errors[name] = err
            fetched[name] = []
        else:
            fetched[name] = _ok_records(records)

    unified_records = []
    for name in _UNIFIED_SOURCES:
        unified_records.extend(fetched.get(name) or [])
    raw_records = []
    for name in _FETCH_TOOLS:
        raw_records.extend(fetched.get(name) or [])

    write_errors: dict[str, str] = {}
    inserted = 0
    if unified_records:
        writes = await _call(
            tools,
            "write_transactions",
            user_id=user_id,
            source=STRIPE,
            transactions=unified_records,
        )
        head = writes[0] if writes else {"error": "write_transactions returned nothing"}
        if "error" in head:
            write_errors["unified"] = head["error"]
        else:
            inserted += head.get("inserted", 0)
    if raw_records:
        writes = await _call(tools, "write_stripe_transactions", user_id=user_id, records=raw_records)
        head = writes[0] if writes else {"error": "write_stripe_transactions returned nothing"}
        if "error" in head:
            write_errors["raw"] = head["error"]

    errors = {**fetch_errors, **write_errors}
    status = "healthy" if not errors else "error"
    await _call(
        tools,
        "mark_sync_status",
        user_id=user_id,
        source=STRIPE,
        status=status,
        record_count=inserted,
        error_message="; ".join(f"{k}: {v}" for k, v in errors.items()) or None,
    )

    return {
        "source": STRIPE,
        "sync_result": {
            "success": not errors,
            "source": STRIPE,
            "record_count": inserted,
            "fetched": {name: len(rows) for name, rows in fetched.items()},
            "errors": errors or None,
        },
    }