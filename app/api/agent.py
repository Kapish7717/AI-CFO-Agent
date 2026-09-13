"""AI Agent endpoint — runs the full CFO workflow via the autonomous ReAct agent.

The agent (LangGraph) connects to the MCP server tools and autonomously
executes: ingest → detect anomalies → generate report → email.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import get_active_user_id

logger = logging.getLogger("cfo.api.agent")

router = APIRouter()


class AgentRunRequest(BaseModel):
    to_email: str | None = None


@router.post("/api/agent/run")
async def agent_run(req: AgentRunRequest, user_id: int = Depends(get_active_user_id)):
    """Run the full CFO pipeline via the autonomous agent."""
    from app.db.database import get_user_settings

    settings = await asyncio.to_thread(get_user_settings, user_id)
    expense = settings.get("expense_url") or settings.get("expense_file_path")
    revenue = settings.get("revenue_url") or settings.get("revenue_file_path")

    if not expense:
        return {
            "success": False,
            "message": "No expense data found. Upload your financial sheets first.",
        }

    email = req.to_email or settings.get("report_email")

    message = f"USER_ID: {user_id}\n\n"
    message += "Run the full CFO workflow:\n"
    message += f"EXPENSE_FILE_PATH: {expense}\n"
    if revenue:
        message += f"REVENUE_FILE_PATH: {revenue}\n"
    if email:
        message += f"Send the report to {email}\n"

    try:
        from app.agents.cfo_agent import graph
        from langchain_core.messages import HumanMessage

        result = await graph.ainvoke({"messages": [HumanMessage(content=message)]})
        final_msg = result["messages"][-1].content
        return {"success": True, "message": final_msg}
    except Exception as e:
        logger.error("Agent run failed for user %s: %s", user_id, e, exc_info=True)
        return {"success": False, "message": f"Agent run failed: {e}"}
