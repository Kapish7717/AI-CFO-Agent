# ==========================================================
# Supervisor graph (Step 6: route on trigger, then delegate to a subgraph)
# ==========================================================
# The supervisor only decides *which* subgraph runs. It never does business
# work and it never decides whether to dispatch: whether an email or a calendar
# event is sent is driven by state (report_email / meeting), not by the trigger,
# so a "scheduled" run and a "new_data" run with the same state behave alike.
#
#   START -> supervisor -> route_after_trigger
#                              |- "pipeline" -> pipeline subgraph (ingest/anomaly/report)
#                              |- "analyst"  -> analyst subgraph
#                              |- "end"      -> END (unknown trigger, error in route_error)

from langgraph.graph import END, START, StateGraph

from app.graph.analyst_node import build_analyst_graph
from app.graph.pipeline import build_graph as build_pipeline_graph
from app.graph.state import PipelineState

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
    return {"route": route, "route_error": None}


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
