# ==========================================================
# Analyst subgraph (Step 6 placeholder for the "chat" trigger)
# ==========================================================
# Step 6 routes "chat" to this subgraph. It is intentionally a marker, not a
# second RAG implementation: the working path today is answer_with_rag() in
# app/services/rag.py, reached via /api/chat/data-query, and that function still
# queries Supabase directly. Step 7 moves it behind the supabase-mcp read tools
# so the analyst gets the same org scoping and tool contract as every other
# stage, at which point this node is replaced.

from langgraph.graph import END, START, StateGraph

from app.graph.state import PipelineState

UNMIGRATED = (
    "Analyst path is not migrated yet; use /api/chat/data-query. "
    "Step 7 moves RAG behind the supabase-mcp read tools."
)


async def analyst_node(state: PipelineState) -> dict:
    if not state.get("user_id"):
        return {"analyst": {"success": False, "error": "user_id is required"}}
    question = (state.get("question") or "").strip()
    if not question:
        return {"analyst": {"success": False, "error": "question is required"}}
    return {
        "analyst": {
            "success": True,
            "implemented": False,
            "question": question,
            "detail": UNMIGRATED,
        }
    }


def build_analyst_graph():
    builder = StateGraph(PipelineState)
    builder.add_node("analyst", analyst_node)
    builder.add_edge(START, "analyst")
    builder.add_edge("analyst", END)
    return builder.compile()


graph = build_analyst_graph()
