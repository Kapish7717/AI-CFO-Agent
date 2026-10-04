# ==========================================================
# Reporting node: consumes anomaly output, dispatches via reporting-mcp
# ==========================================================
# Deterministic (no LLM in the node itself). Turns the anomaly node's findings
# into report instructions, generates the PDF through reporting-mcp, then
# dispatches over Gmail / Calendar when the run asks for it.
#
# State flow:  anomalies + anomaly_flags + anomaly_result in
#              -> report out ({success, generated, delivered, steps})

import asyncio

from app.graph.mcp_client import get_pipeline_tools
from app.graph.mcp_tools import _call, _ok_records
from app.graph.state import PipelineState

_EMAIL_SUBJECT = "Your CFO report is ready"


def _build_instructions(anomalies: list[dict], anomaly_result: dict) -> str:
    """Deterministic narrative brief for the report generator.

    The generator does the prose; this only states what the graph found, so the
    same anomalies always produce the same brief.
    """
    if not anomalies:
        return (
            "No anomalies were detected in the most recent transactions. "
            "Summarize cash position and note that no unusual spend was flagged."
        )

    severity_counts = anomaly_result.get("severity_counts") or {}
    signals = ", ".join(anomaly_result.get("flags") or []) or "heuristic detectors"
    lines = [
        f"{len(anomalies)} transactions were flagged by {signals}.",
        "Severity breakdown: "
        + (", ".join(f"{k} {v}" for k, v in severity_counts.items()) or "unclassified")
        + ".",
        "Lead the executive summary with the highest-severity items and explain "
        "the likely cause of each (duplicate charge, oversized payment, or a "
        "budget breach).",
    ]

    breaches = [a for a in anomalies if "budget_breach" in (a.get("signals") or [])]
    if breaches:
        top = sorted(breaches, key=lambda a: a.get("amount") or 0, reverse=True)[:5]
        lines.append("Largest budget breaches:")
        for item in top:
            lines.append(
                f"- {item.get('category') or 'uncategorized'}: "
                f"${float(item.get('amount') or 0):,.2f} on "
                f"{item.get('transaction_date', 'unknown date')}"
            )

    duplicates = [a for a in anomalies if a.get("entity") == "unknown"]
    if duplicates:
        lines.append(
            f"{len(duplicates)} flagged rows had no counterparty recorded, so treat "
            "their duplicate classification as low confidence."
        )
    return "\n".join(lines)


def _first(records: list[dict]) -> dict:
    """Take the first usable result, surfacing the real error when there is none.

    A failed tool call arrives as a record carrying ``error``. Discarding it in
    favour of a generic message hid a 300s MCP timeout behind "returned no
    result", so the underlying reason has to be carried through.
    """
    rows = _ok_records(records)
    if rows:
        return rows[0]
    failure = next((r for r in records if isinstance(r, dict) and r.get("error")), None)
    return {"success": False, "error": (failure or {}).get("error", "reporting tool returned no result")}


async def reporting_node(state: PipelineState) -> dict:
    """Generate the CFO report and dispatch it when requested."""
    user_id = state.get("user_id")
    if not user_id:
        return {"report": {"success": False, "error": "state['user_id'] is required"}}

    anomalies = state.get("anomalies") or []
    anomaly_result = state.get("anomaly_result") or {}
    tools = await get_pipeline_tools()

    steps: list[dict] = []
    instructions = _build_instructions(anomalies, anomaly_result)
    generated = _first(
        await _call(
            tools,
            "generate_cfo_pdf_report",
            user_id=user_id,
            custom_instructions=instructions,
            start_date=state.get("start_date"),
            end_date=state.get("end_date"),
            report_months=state.get("report_months"),
        )
    )
    steps.append({"step": "generate_cfo_pdf_report", **generated})
    if not generated.get("success"):
        return {
            "report": {
                "success": False,
                "generated": False,
                "delivered": False,
                "error": generated.get("detail") or generated.get("error"),
                "steps": steps,
            }
        }

    delivered = False
    recipient = (state.get("report_email") or "").strip()
    if not recipient:
        from app.db.database import get_user_settings

        settings = await asyncio.to_thread(get_user_settings, user_id)
        recipient = (settings.get("report_email") or "").strip()

    if recipient:
        body = (
            f"Your CFO report is ready. {len(anomalies)} transactions were flagged "
            f"for review."
        )
        sent = _first(
            await _call(
                tools,
                "send_email_report",
                user_id=user_id,
                to_email=recipient,
                subject=_EMAIL_SUBJECT,
                body=body,
            )
        )
        steps.append({"step": "send_email_report", **sent})
        delivered = bool(sent.get("success"))
    else:
        steps.append({"step": "send_email_report", "skipped": "no recipient configured"})

    meeting = state.get("meeting") or {}
    if meeting.get("attendees") and meeting.get("start_time") and meeting.get("end_time"):
        scheduled = _first(
            await _call(
                tools,
                "schedule_budget_review",
                user_id=user_id,
                attendees=meeting["attendees"],
                start_time=meeting["start_time"],
                end_time=meeting["end_time"],
            )
        )
        steps.append({"step": "schedule_budget_review", **scheduled})

    return {
        "report": {
            "success": True,
            "generated": True,
            "delivered": delivered,
            "recipient": recipient or None,
            "anomaly_count": len(anomalies),
            "report_storage_path": generated.get("report_storage_path"),
            "steps": steps,
        }
    }
