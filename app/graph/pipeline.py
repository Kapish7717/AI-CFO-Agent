# ==========================================================
# CFO pipeline graph (Step 4: ingestion -> anomaly -> conditional reporting)
# ==========================================================

from langgraph.graph import END, START, StateGraph

from app.graph.anomaly_node import anomaly_detection_node
from app.graph.ingestion_node import stripe_ingestion_node
from app.graph.reporting_node import reporting_node
from app.graph.state import PipelineState


def route_after_anomaly(state: PipelineState) -> str:
    """Send the run to reporting only when something was actually flagged.

    A failed analysis also routes to END: there is nothing trustworthy to
    report, and the error is already recorded in anomaly_result.
    """
    result = state.get("anomaly_result") or {}
    if not result.get("success"):
        return "end"
    if result.get("anomaly_count", 0) > 0:
        return "reporting"
    return "end"


def build_graph():
    builder = StateGraph(PipelineState)
    builder.add_node("stripe_ingest", stripe_ingestion_node)
    builder.add_node("anomaly_detect", anomaly_detection_node)
    builder.add_node("reporting", reporting_node)

    builder.add_edge(START, "stripe_ingest")
    builder.add_edge("stripe_ingest", "anomaly_detect")
    builder.add_conditional_edges(
        "anomaly_detect",
        route_after_anomaly,
        {"reporting": "reporting", "end": END},
    )
    builder.add_edge("reporting", END)
    return builder.compile()


graph = build_graph()
