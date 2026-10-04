# ==========================================================
# Analyst subgraph (Step 7: chat trigger)
# ==========================================================
# The "chat" trigger lands here. Answering a question is the Text-to-SQL RAG
# service, and that service reads through the supabase-mcp query tools, so this
# node inherits the same org scoping as every other stage. The node is a thin
# adapter: it validates input and hands the answer back on state.
#
# /api/chat/data-query/stream consumes the answer as it is produced, by
# streaming this subgraph through the supervisor with stream_mode="custom".
# A graph node cannot yield, so it writes each chunk to the custom stream and
# still returns the joined answer on state. Run without a stream (ainvoke, a
# unit test) it takes the non-streaming RAG entry point instead.

from langgraph.graph import END, START, StateGraph

from app.graph.state import PipelineState


def _stream_writer():
    """The custom stream writer, or None when there is no active graph run.

    get_stream_writer() raises outside a run, which is the case for a direct
    ainvoke and for unit tests, so the non-streaming path has to stay usable.
    """
    try:
        from langgraph.config import get_stream_writer

        return get_stream_writer()
    except Exception:
        return None


async def analyst_node(state: PipelineState) -> dict:
    if not state.get("user_id"):
        return {"analyst": {"success": False, "error": "user_id is required"}}
    question = (state.get("question") or "").strip()
    if not question:
        return {"analyst": {"success": False, "error": "question is required"}}

    user_id = state["user_id"]
    writer = _stream_writer()
    if writer is None:
        from app.services.rag import answer_with_rag

        answer = await answer_with_rag(user_id=user_id, question=question)
    else:
        from app.services.rag import answer_with_rag_stream

        chunks: list[str] = []
        async for chunk in answer_with_rag_stream(user_id=user_id, question=question):
            writer(chunk)
            chunks.append(chunk)
        answer = "".join(chunks)

    return {"analyst": {"success": True, "question": question, "answer": answer}}


def build_analyst_graph():
    builder = StateGraph(PipelineState)
    builder.add_node("analyst", analyst_node)
    builder.add_edge(START, "analyst")
    builder.add_edge("analyst", END)
    return builder.compile()


graph = build_analyst_graph()
