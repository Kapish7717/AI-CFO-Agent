# ==========================================================
# CFO pipeline graph (Step 3: one-node stripe ingestion)
# ==========================================================

from langgraph.graph import END, START, StateGraph

from app.graph.ingestion_node import stripe_ingestion_node
from app.graph.state import PipelineState


def build_graph():
    builder = StateGraph(PipelineState)
    builder.add_node("stripe_ingest", stripe_ingestion_node)
    builder.add_edge(START, "stripe_ingest")
    builder.add_edge("stripe_ingest", END)
    return builder.compile()


graph = build_graph()