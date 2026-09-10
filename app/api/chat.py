"""Chat API endpoints.

The interactive chat queries the database via Jina RAG (Text-to-SQL) — this is
fully separate from the CFO reporting agent in ``app/api/agent.py``.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import get_active_user_id
from app.db.database import (
    get_connection,
    get_user_chat_history,
    get_user_settings,
    save_user_chat_message,
)

logger = logging.getLogger("cfo.api.chat")

router = APIRouter()

class ChatHistoryResponse(BaseModel):
    sender: str
    text: str
    timestamp: str

@router.get("/api/chat/history", response_model=list[ChatHistoryResponse])
def chat_history(user_id: int = Depends(get_active_user_id)):
    history = get_user_chat_history(user_id)
    if not history:
        return [
            {
                "sender": "agent",
                "text": "Hi! 👋 I've initialized your workspace.\nHow can I help you today?",
                "timestamp": "00:00:00"
            }
        ]
    return history

@router.get("/api/v1/chat/history", response_model=list[ChatHistoryResponse])
def chat_history_v1(user_id: int = Depends(get_active_user_id)):
    return chat_history(user_id)

class DataQueryRequest(BaseModel):
    question: str

@router.post("/api/chat/data-query")
async def chat_data_query(req: DataQueryRequest, user_id: int = Depends(get_active_user_id)):
    """Answer a question about the user's uploaded financial data via Jina RAG.
    Querying the database is fully separate from the CFO reporting agent.
    """
    if not req.question or not req.question.strip():
        return {"answer": "Please type a question about your financial data.", "success": True}
    from app.services.rag import answer_with_rag
    answer = await answer_with_rag(user_id=user_id, question=req.question.strip())
    # Persist the Q&A to chat history so it survives a page refresh.
    try:
        await asyncio.to_thread(save_user_chat_message, user_id, "user", req.question.strip())
        await asyncio.to_thread(save_user_chat_message, user_id, "agent", answer)
    except Exception as e:
        logger.warning("Could not persist chat for user %s: %s", user_id, e)
    return {"answer": answer, "success": True}

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
        rag_response,
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

            sql_prompt = make_sql_prompt(req.question, ranked, user_id=user_id)
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

            answer = await rag_response(req.question, sql_clean, rows, settings)
            result["final_answer"] = answer
        finally:
            conn.close()

    except Exception as e:
        logger.error("Test RAG failed for user %s: %s", user_id, e, exc_info=True)
        result["error"] = str(e)

    return result

