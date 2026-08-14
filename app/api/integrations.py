import logging
import os
import re
import shutil

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.security import get_current_user_id
from app.db.database import get_connection, get_user_settings, update_user_settings
from app.db.unified_store import get_sync_status, update_sync_status
from app.integrations.google_auth import exchange_code_for_token, get_auth_url

logger = logging.getLogger("cfo.api.integrations")

router = APIRouter()

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(WORKSPACE_ROOT, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

_UPLOAD_CHUNK = 1024 * 1024


def _sanitize_filename(filename: str) -> str:
    """Strip directory components and dangerous characters from a filename."""
    base = os.path.basename((filename or "").replace("\\", "/"))
    # Keep only word characters, dots, dashes, underscores, spaces.
    base = re.sub(r"[^\w.\- ]+", "_", base)
    return base.strip() or "upload"


def get_effective_redirect_uri(request: Request) -> str:
    base_url = str(request.base_url).rstrip('/')
    x_forwarded_proto = request.headers.get('x-forwarded-proto')
    if x_forwarded_proto == 'https' and base_url.startswith('http://'):
        base_url = base_url.replace('http://', 'https://', 1)
    return f"{base_url}/auth/callback"


class DataConnectRequest(BaseModel):
    provider: str
    credentials: dict | None = None
    auth_code: str | None = None

@router.post("/api/v1/data/connect")
def connect_data(payload: DataConnectRequest, request: Request, user_id: int = Depends(get_current_user_id)):
    provider = payload.provider.strip().lower()

    if provider in {"google", "google_sheets", "google_drive"}:
        if payload.auth_code:
            redirect_uri = get_effective_redirect_uri(request)
            result = exchange_code_for_token(payload.auth_code, redirect_uri=redirect_uri, user_id=user_id)
            return {"message": result}

        redirect_uri = get_effective_redirect_uri(request)
        return {
            "connect_url": get_auth_url(redirect_uri=redirect_uri, user_id=user_id),
            "instructions": "Open this URL to authenticate the Google connection for the current user.",
        }

    if provider in {"postgresql", "postgres"}:
        try:
            conn = get_connection()
            conn.close()
            return {"message": "PostgreSQL connection verified", "provider": "postgresql"}
        except Exception as exc:
            logger.error("PostgreSQL connection check failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail="Could not verify PostgreSQL connection.") from exc

    if provider == "quickbooks":
        return {"message": "QuickBooks support is not implemented yet. Please use Google Sheets or PostgreSQL for now."}

    raise HTTPException(status_code=400, detail=f"Unsupported provider: {payload.provider}")


@router.post("/api/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    file_type: str = None,
):
    settings = get_settings()
    safe_name = _sanitize_filename(file.filename)
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in settings.allowed_upload_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed extensions: {settings.ALLOWED_UPLOAD_EXTENSIONS}",
        )

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        full_name = f"{user_id}_{safe_name}"

        from app.db.storage import get_storage_client, upload_to_storage
        temp_path = os.path.join(UPLOAD_DIR, f"temp_{full_name}")

        written = 0
        with open(temp_path, "wb") as buffer:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    buffer.close()
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {settings.MAX_UPLOAD_MB}MB upload limit.",
                    )
                buffer.write(chunk)

        if get_storage_client():
            cloud_path = f"uploads/{full_name}"
            try:
                clean_path = upload_to_storage(temp_path, cloud_path)
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
        else:
            file_path = os.path.join(UPLOAD_DIR, full_name)
            if temp_path != file_path:
                shutil.move(temp_path, file_path)
            else:
                os.rename(temp_path, file_path)
            clean_path = os.path.abspath(file_path).replace("\\", "/")

        if file_type in ("expense", "revenue"):
            if file_type == "expense":
                update_user_settings(user_id, {
                    "expense_file_path": clean_path,
                    "expense_file_name": safe_name,
                })
            else:
                update_user_settings(user_id, {
                    "revenue_file_path": clean_path,
                    "revenue_file_name": safe_name,
                })
            background_tasks.add_task(_ingest_uploaded_data, user_id)

        return {"file_path": clean_path, "filename": safe_name}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Upload failed for user %s: %s", user_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to upload file.") from e


async def _ingest_uploaded_data(user_id: int):
    """Ingest the user's uploaded sheets and refresh budget breaches."""
    try:
        from app.services.agent_runner import ingest_user_data
        result = await ingest_user_data(user_id)
        if not result.get("success"):
            logger.warning("Upload ingest failed for user %s: %s", user_id, result.get("message"))
    except Exception as e:
        logger.error("Upload ingest error for user %s: %s", user_id, e, exc_info=True)


# ---------- Stripe connect / status / disconnect ----------

class StripeConnectRequest(BaseModel):
    api_key: str

@router.post("/api/integrations/stripe/connect")
def stripe_connect(payload: StripeConnectRequest, user_id: int = Depends(get_current_user_id)):
    api_key = (payload.api_key or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="Stripe API key is required")

    # Validate the key before persisting it.
    try:
        import stripe
        stripe.api_key = api_key
        stripe.Charge.list(limit=1)
    except Exception as e:
        logger.warning("Stripe key rejected for user %s: %s", user_id, e)
        raise HTTPException(status_code=400, detail="Stripe key rejected. Please check the key and try again.") from e

    update_user_settings(user_id, {"stripe_secret_key": api_key})

    from app.services.stripe_sync import sync_stripe_charges
    result = sync_stripe_charges(user_id, api_key)
    if not result.get("success"):
        return {
            "connected": True,
            "source": "stripe",
            "synced": 0,
            "total": 0,
            "error": result.get("error"),
        }

    return {
        "connected": True,
        "source": "stripe",
        "synced": result.get("synced", 0),
        "total": result.get("total", 0),
    }

@router.get("/api/integrations/stripe/status")
def stripe_status(user_id: int = Depends(get_current_user_id)):
    settings = get_user_settings(user_id)
    connected = bool((settings.get("stripe_secret_key") or "").strip())
    info = {
        "connected": connected,
        "status": None,
        "last_synced_at": None,
        "record_count": None,
        "error_message": None,
    }
    if connected:
        try:
            row = get_sync_status("stripe")
            if row:
                info["status"] = row.get("status")
                info["last_synced_at"] = (
                    row.get("last_synced_at").isoformat() if row.get("last_synced_at") else None
                )
                info["record_count"] = row.get("record_count")
                info["error_message"] = row.get("error_message")
        except Exception:
            logger.warning("Could not load Stripe sync status for user %s", user_id, exc_info=True)
    return info

@router.post("/api/integrations/stripe/disconnect")
def stripe_disconnect(user_id: int = Depends(get_current_user_id)):
    update_user_settings(user_id, {"stripe_secret_key": None})
    try:
        update_sync_status(source="stripe", status="disconnected", record_count=None)
    except Exception as e:
        logger.warning("Stripe disconnect status update failed: %s", e)
    return {"success": True, "connected": False}