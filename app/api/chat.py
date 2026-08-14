"""Chat API endpoints.

The interactive chat queries the database via Jina RAG (Text-to-SQL) — this is
fully separate from the CFO reporting agent in ``app/api/agent.py``.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import get_current_user_id
from app.db.database import get_user_chat_history, save_user_chat_message

logger = logging.getLogger("cfo.api.chat")

router = APIRouter()

class ChatHistoryResponse(BaseModel):
    sender: str
    text: str
    timestamp: str

@router.get("/api/chat/history", response_model=list[ChatHistoryResponse])
def chat_history(user_id: int = Depends(get_current_user_id)):
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
def chat_history_v1(user_id: int = Depends(get_current_user_id)):
    return chat_history(user_id)

class DataQueryRequest(BaseModel):
    question: str

@router.post("/api/chat/data-query")
async def chat_data_query(req: DataQueryRequest, user_id: int = Depends(get_current_user_id)):
    """Answer a question about the user's uploaded financial data via Jina RAG.
    Querying the database is fully separate from the CFO reporting agent.
    """
    if not req.question or not req.question.strip():
        return {"answer": "Please type a question about your financial data.", "success": True}
    from app.services.rag import answer_with_rag
    answer = await answer_with_rag(user_id=user_id, question=req.question.strip())
    # Persist the Q&A to chat history so it survives a page refresh.
    try:
        save_user_chat_message(user_id, "user", req.question.strip())
        save_user_chat_message(user_id, "agent", answer)
    except Exception as e:
        logger.warning("Could not persist chat for user %s: %s", user_id, e)
    return {"answer": answer, "success": True}