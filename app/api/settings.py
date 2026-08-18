import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import get_current_user_id, mask_secret
from app.db.database import get_user_settings, update_user_settings

logger = logging.getLogger("cfo.api.settings")

router = APIRouter()

class UserSettingsUpdate(BaseModel):
    budget_marketing: float | None = None
    budget_operations: float | None = None
    budget_travel: float | None = None
    expense_file_path: str | None = None
    expense_file_name: str | None = None
    expense_url: str | None = None
    revenue_file_path: str | None = None
    revenue_file_name: str | None = None
    revenue_url: str | None = None
    selected_month: str | None = None
    llm_primary_provider: str | None = None
    llm_primary_model: str | None = None
    llm_fallback_provider: str | None = None
    llm_fallback_model: str | None = None
    api_key: str | None = None
    fallback_api_key: str | None = None
    report_email: str | None = None
    report_schedule: str | None = None

@router.get("/api/user-settings")
def get_settings(user_id: int = Depends(get_current_user_id)):
    settings = get_user_settings(user_id)
    return {
        "budget_marketing": float(settings["budget_marketing"]) if settings["budget_marketing"] else 5000.0,
        "budget_operations": float(settings["budget_operations"]) if settings["budget_operations"] else 8000.0,
        "budget_travel": float(settings["budget_travel"]) if settings["budget_travel"] else 2000.0,
        "expense_file_path": settings["expense_file_path"],
        "expense_file_name": settings["expense_file_name"],
        "expense_url": settings["expense_url"],
        "revenue_file_path": settings["revenue_file_path"],
        "revenue_file_name": settings["revenue_file_name"],
        "revenue_url": settings["revenue_url"],
        "selected_month": settings["selected_month"],
        "llm_primary_provider": settings.get("llm_primary_provider") or "mock",
        "llm_primary_model": settings.get("llm_primary_model"),
        "llm_fallback_provider": settings.get("llm_fallback_provider"),
        "llm_fallback_model": settings.get("llm_fallback_model"),
        "api_key": mask_secret(settings.get("api_key")),
        "fallback_api_key": mask_secret(settings.get("fallback_api_key")),
        "report_email": settings.get("report_email"),
        "report_schedule": settings.get("report_schedule")
    }

@router.post("/api/user-settings")
def update_settings(updates: UserSettingsUpdate, user_id: int = Depends(get_current_user_id)):
    try:
        update_user_settings(user_id, updates.dict(exclude_unset=True))
        # Recompute + push budget breaches so the agent always reads fresh data.
        if any(updates.dict(exclude_unset=True).get(k) is not None for k in ("budget_marketing", "budget_operations", "budget_travel")):
            from app.services.budget_breaches import refresh_budget_breaches
            refresh_budget_breaches(user_id)
        return {"success": True}
    except Exception as e:
        logger.error(f"Settings update failed for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update settings.") from e