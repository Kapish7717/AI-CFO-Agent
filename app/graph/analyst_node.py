# ==========================================================
# Analyst subgraph (Step 7: chat trigger)
# ==========================================================
# The "chat" trigger lands here. Answering a question is the Text-to-SQL RAG
# service, and that service reads through the supabase-mcp query tools, so this
# node inherits the same org scoping as every other stage. The node is a thin
# adapter: it validates input and hands the answer back on state.
#
# The API's streaming variant of the same pipeline is
# /api/chat/data-query/stream; a graph node cannot stream, so it uses the
# non-streaming entry point.

from langgraph.graph import END, START, StateGraph

from app.graph.state import PipelineState


async def analyst_node(state: PipelineState) -> dict:
    if not state.get("user_id"):
        return {"analyst": {"success": False, "error": "user_id is required"}}
    question = (state.get("question") or "").strip()
    if not question:
        return {"analyst": {"success": False, "error": "question is required"}}

    from app.services.rag import answer_with_rag

    answer = await answer_with_rag(user_id=state["user_id"], question=question)
    return {"analyst": {"success": True, "question": question, "answer": answer}}


def build_analyst_graph():
    builder = StateGraph(PipelineState)
    builder.add_node("analyst", analyst_node)
    builder.add_edge(START, "analyst")
    builder.add_edge("analyst", END)
    return builder.compile()


graph = build_analyst_graph()
