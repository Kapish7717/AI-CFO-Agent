"""AI Agent endpoints for CFO financial reporting only.

The interactive chat ("query the database") is served by the Jina RAG endpoint
in ``app/api/chat.py`` and is intentionally separate from the agent here.

The agent below drives the full CFO reporting pipeline (ingest -> detect ->
generate report -> email).
"""


from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import get_current_user_id
from app.services.agent_runner import run_cfo_pipeline

router = APIRouter()


class AgentRunRequest(BaseModel):
    to_email: str | None = None


@router.post("/api/agent/run")
async def agent_run(req: AgentRunRequest, user_id: int = Depends(get_current_user_id)):
    """Run the full CFO pipeline (ingest -> detect -> report -> email)."""
    result = await run_cfo_pipeline(user_id=user_id, to_email=req.to_email)
    return result