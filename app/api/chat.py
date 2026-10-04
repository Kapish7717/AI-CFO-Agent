"""Chat API endpoints.

Questions are answered by the analyst subgraph of the CFO graph
(``app/graph/supervisor.py``): this router hands the supervisor a ``chat``
trigger and reads the answer back off state, so chat goes through the same
routing, org scoping and MCP tooling as the reporting run instead of calling
the RAG service directly.
"""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import get_active_user_id
from app.db.database import (
    clear_user_chat_history,
    get_connection,
    get_user_chat_history,
    get_user_settings,
    save_user_chat_message,
)

logger = logging.getLogger("cfo.api.chat")

router = APIRouter()

_ASK_HINT = "Please type a question about your financial data."

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Without this nginx buffers the whole response and the stream arrives at once.
    "X-Accel-Buffering": "no",
}


def _chat_state(user_id: int, question: str) -> dict:
    """The supervisor input that routes to the analyst subgraph."""
    return {"user_id": user_id, "trigger": "chat", "question": question}

class ChatHistoryResponse(BaseModel):
    sender: str
    text: str
    id: int
    timestamp: str

@router.get("/api/chat/history", response_model=list[ChatHistoryResponse])
def chat_history(user_id: int = Depends(get_active_user_id)):
    return get_user_chat_history(user_id)

@router.get("/api/v1/chat/history", response_model=list[ChatHistoryResponse])
def chat_history_v1(user_id: int = Depends(get_active_user_id)):
    return chat_history(user_id)

@router.delete("/api/chat/history")
def clear_chat_history(user_id: int = Depends(get_active_user_id)):
    clear_user_chat_history(user_id)
    return {"success": True}

class DataQueryRequest(BaseModel):
    question: str

@router.post("/api/chat/data-query")
async def chat_data_query(req: DataQueryRequest, user_id: int = Depends(get_active_user_id)):
    """Answer a question about the user's uploaded financial data via the graph.

    The ``chat`` trigger routes to the analyst subgraph, which reads through the
    supabase-mcp query tools, so the answer is scoped to the caller's org.
    """
    if not req.question or not req.question.strip():
        return {"answer": _ASK_HINT, "success": True}

    from app.graph.supervisor import graph

    result = await graph.ainvoke(_chat_state(user_id, req.question.strip()))
    analyst = result.get("analyst") or {}
    answer = analyst.get("answer") or analyst.get("error") or ""
    success = bool(analyst.get("success"))
    if not success:
        logger.warning("Analyst run failed for user %s: %s", user_id, analyst.get("error"))

    await _persist_exchange(user_id, req.question.strip(), answer)
    return {"answer": answer, "success": success}


async def _persist_exchange(user_id: int, question: str, answer: str) -> None:
    """Save the Q&A so it survives a page refresh. Never fails the request."""
    try:
        await asyncio.to_thread(save_user_chat_message, user_id, "user", question)
        await asyncio.to_thread(save_user_chat_message, user_id, "agent", answer)
    except Exception as e:
        logger.warning("Could not persist chat for user %s: %s", user_id, e)


@router.post("/api/chat/data-query/stream")
async def chat_data_query_stream(req: DataQueryRequest, user_id: int = Depends(get_active_user_id)):
    """Stream the analyst's answer as SSE frames: ``data: {"chunk": ...}`` lines.

    Canonical chat entry point: the frontend consumes this endpoint. The graph is
    streamed with stream_mode="custom" so the analyst node's chunks arrive as
    they are produced, and with "values" alongside it so the final state is read
    back off the graph rather than reassembled here.
    """
    from fastapi.responses import StreamingResponse

    question = (req.question or "").strip()
    if not question:

        async def hint():
            yield f"data: {json.dumps({'chunk': _ASK_HINT})}\n\n"
            yield f"data: {json.dumps({'done': True, 'answer': _ASK_HINT})}\n\n"

        return StreamingResponse(hint(), media_type="text/event-stream", headers=_SSE_HEADERS)

    from app.graph.supervisor import graph

    async def event_generator():
        full_answer = ""
        final_state: dict = {}
        try:
            async for mode, chunk in graph.astream(
                _chat_state(user_id, question), stream_mode=["custom", "values"]
            ):
                if mode == "custom":
                    if isinstance(chunk, str) and chunk:
                        full_answer += chunk
                        yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                elif mode == "values" and isinstance(chunk, dict):
                    final_state = chunk
        except Exception as e:
            logger.error("Chat stream failed for user %s: %s", user_id, e, exc_info=True)
            full_answer = f"Data query failed: {e}"
            yield f"data: {json.dumps({'chunk': full_answer})}\n\n"

        answer = (final_state.get("analyst") or {}).get("answer") or full_answer
        await _persist_exchange(user_id, question, answer)
        yield f"data: {json.dumps({'done': True, 'answer': answer})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers=_SSE_HEADERS)


class TestRagRequest(BaseModel):
    question : str
    provider : str | None = None
    model: str | None = None
    api_key: str | None = None
    top_n: int = 3
    skip_rerank: bool = False 

@router.post("/api/chat/test-rag")
async def test_rag(req: TestRagRequest, user_id : int = Depends(get_active_user_id)):
    from app.services.rag import (
        _llm_for,
        _read_only,
        extract_schema,
        make_sql_prompt,
        rag_response_stream,
        rank_tables,
        sql_response,
    )

    result = {
        "question": req.question,
        "schema_extracted": [], 
        "ranked_tables": [],
        "sql_prompt": None,
        "generated_sql": None,
        "sql_clean": None,
        "read_only_check": None,
        "sql_result": None,
        "final_answer": None,
        "error": None,
    }

    try:
        settings = await asyncio.to_thread(get_user_settings,user_id)
        if req.provider:
            settings['llm_primary_provider'] = req.provider
        if req.model:
            settings["llm_primary_model"] = req.model
        if req.api_key:
            settings["api_key"] = req.api_key

        conn = await asyncio.to_thread(get_connection)
        try:
            table_specs = await asyncio.to_thread(extract_schema,conn)
            result['schema_extracted'] = table_specs
            if not table_specs:
                result['error'] = "No database tables found"
                return result

            if req.skip_rerank:
                ranked=[(0.0,spec) for spec in table_specs]

            else:
                ranked = await rank_tables(req.question, table_specs,top_n=req.top_n)
                result['ranked_tables'] = [{
                    "score": s,
                    "schema": s2
                } for s,s2 in ranked]

            history = await asyncio.to_thread(get_user_chat_history, user_id, 10)
            sql_prompt = make_sql_prompt(req.question, ranked, user_id=user_id, history=history)
            result["sql_prompt"] = sql_prompt
            llm = _llm_for(settings)

            from app.services.llm_factory import generate_text
            sql_raw = await generate_text(llm,sql_prompt)
            result['generated_sql'] = sql_raw

            sql_clean = sql_raw.replace("```sql", "").replace("```", "").strip()
            result["sql_clean"] = sql_clean

            is_read_only = _read_only(sql_clean)
            result["read_only_check"] = is_read_only
            if not is_read_only:
                result["error"] = "SQL failed read-only check"
                return result

            rows = await asyncio.to_thread(sql_response, sql_clean, conn)
            result["sql_result"] = rows

            answer = ""
            async for chunk in rag_response_stream(req.question, sql_clean, rows, settings, history=history):
                answer += chunk
            result["final_answer"] = answer
        finally:
            conn.close()

    except Exception as e:
        logger.error("Test RAG failed for user %s: %s", user_id, e, exc_info=True)
        result["error"] = str(e)

    return result

