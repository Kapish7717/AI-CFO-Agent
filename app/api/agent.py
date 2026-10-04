"""AI Agent endpoint — runs the full CFO workflow through the supervisor graph.

The graph is driven by state, not by a prose prompt: this endpoint hands the
supervisor a ``new_data`` trigger with the user's own ``report_months`` and
``report_email``, and the graph runs anomaly -> report -> email. It is the same
entry the scheduler uses (``app/main.py``), so a manual run and a scheduled run
cannot diverge. Transactions are read from Supabase, which the 60s Stripe loop
and the Stripe webhook keep current; nothing here writes them.
"""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import get_active_user_id

logger = logging.getLogger("cfo.api.agent")

router = APIRouter()

_EMPTY_ANSWER = "Nothing to report yet — upload your financial sheets first."


class AgentRunRequest(BaseModel):
    to_email: str | None = None


def _summarise(result: dict) -> tuple[bool, str]:
    """Turn the graph's state into the success flag and the message the UI shows.

    A clean period is a success, not a failure: a run that found nothing still
    reports (force_report), so the report always exists to point at.
    """
    report = result.get("report") or {}
    anomaly = result.get("anomaly_result") or {}

    if result.get("route_error"):
        return False, result["route_error"]

    if report:
        if not report.get("success"):
            return False, report.get("error") or "Report generation failed."
        flagged = report.get("anomaly_count", 0)
        if report.get("delivered"):
            delivery = f" emailed to {report['recipient']}."
        else:
            delivery = " Not emailed — no report email is configured."
        return True, f"Report generated for {flagged} flagged transactions.{delivery}"

    if anomaly and not anomaly.get("success"):
        return False, anomaly.get("error") or "Anomaly analysis failed."

    return False, _EMPTY_ANSWER


def _steps(result: dict) -> list[dict]:
    """Flatten the graph's per-stage output into the step list the UI renders."""
    steps: list[dict] = []

    anomaly = result.get("anomaly_result") or {}
    if anomaly:
        steps.append(
            {
                "step": "anomaly_detect",
                "message": f"{anomaly.get('anomaly_count', 0)} anomalies in "
                f"{anomaly.get('rows_analyzed', 0)} rows",
            }
        )

    for step in (result.get("report") or {}).get("steps") or []:
        detail = step.get("error") or step.get("skipped") or step.get("detail")
        # A tool can report a failure either as success=False or by carrying an
        # error alongside a missing flag, so both have to be checked before a
        # step is reported as done.
        if step.get("success") is False or step.get("error"):
            message = f"failed: {detail}"
        elif step.get("skipped"):
            message = f"skipped ({detail})"
        else:
            message = "ok"
        steps.append({"step": step.get("step", "report"), "message": message})

    return steps


@router.post("/api/agent/run")
async def agent_run(req: AgentRunRequest, user_id: int = Depends(get_active_user_id)):
    """Run the full CFO pipeline through the supervisor graph."""
    from app.db.database import get_user_settings

    settings = await asyncio.to_thread(get_user_settings, user_id)
    expense = settings.get("expense_url") or settings.get("expense_file_path")
    if not expense and not (settings.get("stripe_secret_key") or "").strip():
        return {"success": False, "message": "No financial data found. Upload sheets or connect Stripe first."}

    from app.graph.supervisor import graph

    state = {
        "user_id": user_id,
        "trigger": "new_data",
        "source": "stripe",
        # Somebody pressed the button, so report even when nothing was flagged.
        "force_report": True,
    }
    recipient = (req.to_email or "").strip() or (settings.get("report_email") or "").strip()
    if recipient:
        state["report_email"] = recipient

    run_started = time.perf_counter()
    try:
        result = await graph.ainvoke(state)
    except Exception as e:
        logger.error("CFO run failed for user %s: %s", user_id, e, exc_info=True)
        return {"success": False, "message": f"CFO run failed: {e}", "steps": []}
    logger.info(
        "CFO run finished for user %s in %.0fms", user_id, (time.perf_counter() - run_started) * 1000.0
    )

    success, message = _summarise(result)
    steps = _steps(result)
    if not steps:
        steps = [{"step": "cfo_run", "message": message}]
    return {"success": success, "message": message, "steps": steps}
