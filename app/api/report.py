import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.agents.mcp_server import generate_cfo_pdf_report, get_user_state_paths
from app.core.security import get_current_user_id
from app.db.database import get_user_transactions
from app.db.storage import download_from_storage

router = APIRouter()

class ReportRequest(BaseModel):
    custom_instructions: str | None = None

@router.post("/api/v1/report")
async def generate_report_endpoint(payload: ReportRequest, user_id: int = Depends(get_current_user_id)):
    rows = get_user_transactions(user_id)
    if not rows:
        raise HTTPException(status_code=400, detail="No data available. Please ingest financial data first.")

    result = await generate_cfo_pdf_report(payload.custom_instructions or "", user_id=user_id)
    return {"success": True, "message": result}

@router.get("/api/download-report")
def download_report_endpoint(user_id: int = Depends(get_current_user_id)):
    _, report_file, _ = get_user_state_paths(user_id)

    # Try downloading PDF report from Supabase Storage
    try:
        download_from_storage(f"reports/executive_cfo_report_{user_id}.pdf", report_file)
    except Exception:
        pass

    if os.path.exists(report_file):
        return FileResponse(report_file, media_type="application/pdf", filename=os.path.basename(report_file))
    raise HTTPException(status_code=404, detail="Report not found.")

@router.get("/api/v1/report/download")
def download_report_v1(user_id: int = Depends(get_current_user_id)):
    return download_report_endpoint(user_id)