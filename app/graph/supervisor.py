# ==========================================================
# Supervisor graph (Step 6: route on trigger, then delegate to a subgraph)
# ==========================================================
# The supervisor only decides *which* subgraph runs. It never does business
# work and it never decides whether to dispatch: whether an email or a calendar
# event is sent is driven by state (report_email / meeting), not by the trigger,
# so a "scheduled" run and a "new_data" run with the same state behave alike.
#
# This is the graph every entry point invokes — the scheduler, the manual run
# endpoint and chat — so there is one routing story and one set of nodes.
#
#   START -> supervisor -> route_after_trigger
#                              |- "pipeline" -> pipeline subgraph (anomaly/report)
#                              |- "analyst"  -> analyst subgraph
#                              |- "end"      -> END (unknown trigger, error in route_error)

from __future__ import annotations

import asyncio
import logging

from langgraph.graph import END, START, StateGraph

from app.graph.analyst_node import build_analyst_graph
from app.graph.period import normalize_months, resolve_window
from app.graph.pipeline import build_graph as build_pipeline_graph
from app.graph.state import PipelineState

logger = logging.getLogger("cfo.graph.supervisor")

#: trigger -> subgraph. Data triggers share the pipeline; chat goes to the analyst.
ROUTES = {
    "new_data": "pipeline",
    "scheduled": "pipeline",
    "chat": "analyst",
}


async def supervisor_node(state: PipelineState) -> dict:
    trigger = (state.get("trigger") or "").strip()
    route = ROUTES.get(trigger)
    if route is None:
        return {
            "route": None,
            "route_error": (
                f"unknown trigger {trigger!r}; expected one of {sorted(ROUTES)}"
            ),
        }

    # Data triggers also resolve the reporting window here, so the anomaly pass
    # and the report generator read the same bounds instead of each deciding.
    if route == "pipeline":
        return {**await _resolve_report_window(state), "route": route, "route_error": None}
    return {"route": route, "route_error": None}


async def _resolve_report_window(state: PipelineState) -> dict:
    """Work out how many months to report on and the ISO bounds that implies."""
    user_id = state.get("user_id")
    months = state.get("report_months")
    if months is None and user_id is not None:
        try:
            from app.db.database import get_user_settings

            settings = await asyncio.to_thread(get_user_settings, user_id)
            months = (settings or {}).get("report_months")
        except Exception:
            logger.warning("[supervisor] falling back to default period", exc_info=True)
            months = None

    count = normalize_months(months)
    anchor = None
    if user_id is not None:
        try:
            from app.db.database import get_max_transaction_date

            anchor = await asyncio.to_thread(get_max_transaction_date, user_id)
        except Exception:
            logger.warning("[supervisor] could not read the newest transaction date", exc_info=True)
    start_date, end_date = resolve_window(count, anchor)
    return {
        "report_months": count,
        "start_date": start_date,
        "end_date": end_date,
    }


def route_after_trigger(state: PipelineState) -> str:
    return state.get("route") or "end"


def build_graph():
    builder = StateGraph(PipelineState)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("pipeline", build_pipeline_graph())
    builder.add_node("analyst", build_analyst_graph())

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        route_after_trigger,
        {"pipeline": "pipeline", "analyst": "analyst", "end": END},
    )
    builder.add_edge("pipeline", END)
    builder.add_edge("analyst", END)
    return builder.compile()


graph = build_graph()
