from fastapi import APIRouter, Depends

from app.core.security import get_current_user_id
from app.services.ai_service import list_models, list_providers

router = APIRouter()

@router.get("/api/v1/providers")
def get_providers_v1(_user_id: int = Depends(get_current_user_id)):
    """Return the list of supported LLM providers."""
    return {"providers": list_providers()}

@router.get("/api/providers")
def get_providers(_user_id: int = Depends(get_current_user_id)):
    return get_providers_v1(_user_id=_user_id)

@router.get("/api/v1/models")
def get_models_v1(provider: str, api_key: str | None = None, _user_id: int = Depends(get_current_user_id)):
    """Return available model names for a given provider.

    When ``api_key`` is supplied the provider's live API is queried for
    real-time model names; otherwise a curated static list is returned.
    """
    return {"models": list_models(provider, api_key=api_key)}

@router.get("/api/models")
def get_models(provider: str, api_key: str | None = None, _user_id: int = Depends(get_current_user_id)):
    return get_models_v1(provider, api_key=api_key, _user_id=_user_id)