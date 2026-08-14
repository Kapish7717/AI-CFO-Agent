from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.agent import router as agent_router
from app.api.anomaly import router as anomaly_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.dashboard import router as dashboard_router
from app.api.forecast import router as forecast_router
from app.api.integrations import router as integrations_router
from app.api.providers import router as providers_router
from app.api.report import router as report_router
from app.api.settings import router as settings_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import get_current_user, mask_secret
from app.services.llm_factory import create_llm, generate_text
from app.services.session_manager import default_manager

# Load environment variables (.env) before any module reads them.
load_dotenv()

settings = get_settings()
configure_logging(level=settings.LOG_LEVEL, log_dir=settings.LOG_DIR)
logger = logging.getLogger("cfo.api.main")


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate_production()

    # Initialise the database schema (best-effort; failures are logged loudly).
    from app.db.database import close_all_pooled_connections, init_db

    try:
        init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error("Database initialization failed: %s", e, exc_info=True)
        raise

    # Start the background loops; each is a long-lived, self-healing task.
    tasks = [
        asyncio.create_task(_scheduled_report_loop()),
        asyncio.create_task(_stripe_sync_loop()),
    ]
    logger.info("Background loops scheduled.")
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            close_all_pooled_connections()
        except Exception:
            logger.warning("Error closing DB pool during shutdown", exc_info=True)
        logger.info("Shutdown complete.")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# CORS: explicit origin allow-list; credentials are never combined with "*".
origins = settings.cors_origins
if "*" in origins:
    logger.warning(
        "CORS_ORIGINS contains '*'; this is only acceptable for development. "
        "Set explicit origins in production."
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include routers (their decorators define absolute paths).
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(dashboard_router)
app.include_router(forecast_router)
app.include_router(anomaly_router)
app.include_router(integrations_router)
app.include_router(providers_router)
app.include_router(report_router)
app.include_router(settings_router)
app.include_router(agent_router)


# --------------------------------------------------------------------------- #
# Background loops
# --------------------------------------------------------------------------- #
_report_last_run: dict = {}


async def _run_scheduled_pipeline(user_id: int):
    """Run one user's CFO pipeline in a detached background task."""
    try:
        from app.services.agent_runner import run_cfo_pipeline
        result = await run_cfo_pipeline(user_id=user_id)
        logger.info("[SCHEDULER] Pipeline result for user %s: %s", user_id, result.get("message"))
    except Exception as e:
        logger.error("[SCHEDULER] Pipeline failed for user %s: %s", user_id, e)


async def _scheduled_report_loop():
    """Every 60s, run the CFO pipeline for users whose report_schedule (HH:MM)
    matches the current time. Each user runs at most once per day."""
    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            hhmm = now.strftime("%H:%M")

            from app.db.database import get_all_user_ids, get_user_settings
            user_ids = await asyncio.to_thread(get_all_user_ids)
            for user_id in user_ids:
                try:
                    settings_row = await asyncio.to_thread(get_user_settings, user_id)
                    schedule = (settings_row.get("report_schedule") or "").strip()
                    email = (settings_row.get("report_email") or "").strip()
                    if not schedule or not email:
                        continue
                    if schedule[:5] != hhmm:
                        continue
                    if _report_last_run.get(user_id) == today:
                        continue
                    _report_last_run[user_id] = today
                    logger.info("[SCHEDULER] Triggering report for user %s at %s.", user_id, hhmm)
                    asyncio.create_task(_run_scheduled_pipeline(user_id))
                except Exception as e:
                    logger.error("[SCHEDULER] Error checking user %s: %s", user_id, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[SCHEDULER] Loop error: %s", e)

        await asyncio.sleep(60)


async def _stripe_sync_loop():
    """Every 60s, pull new Stripe charges for all connected users. Idempotent
    thanks to the (external_id, source) unique constraint."""
    while True:
        try:
            from app.services.stripe_sync import sync_all_users
            await asyncio.to_thread(sync_all_users)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[STRIPE SYNC] Loop error: %s", e)
        await asyncio.sleep(60)


# --------------------------------------------------------------------------- #
# Health / readiness
# --------------------------------------------------------------------------- #
@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/healthz")
def readiness_check():
    """Readiness probe: confirms the database is reachable."""
    from app.db.database import get_connection
    try:
        conn = get_connection()
        conn.close()
        return {"status": "ready"}
    except Exception as e:
        logger.error("Readiness check failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Database not ready.") from e


# --------------------------------------------------------------------------- #
# LLM test utility (development aid, requires authentication)
# --------------------------------------------------------------------------- #
class TestLLMRequest(BaseModel):
    session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    prompt: str
    save_session: bool = False


class TestLLMResponse(BaseModel):
    session_id: str | None
    provider: str | None
    model: str | None
    reply: str


@app.post("/api/test-llm", response_model=TestLLMResponse)
async def test_llm(req: TestLLMRequest, _user: dict = Depends(get_current_user)):
    cfg = None
    if req.session_id:
        cfg = default_manager.get_session(req.session_id)

    if cfg is None:
        if not (req.provider and req.api_key):
            raise HTTPException(status_code=400, detail="No session found and provider/api_key not provided")
        cfg = {"provider": req.provider, "model": req.model, "api_key": req.api_key}

    if req.save_session and req.session_id:
        default_manager.set_session(req.session_id, cfg)

    try:
        llm = create_llm(provider=cfg.get("provider"), model=cfg.get("model"), api_key=cfg.get("api_key"))
    except Exception as e:
        logger.error("LLM creation failed: %s", e)
        raise HTTPException(status_code=500, detail="Could not initialise the LLM provider.") from e

    reply = await generate_text(llm, req.prompt)
    return TestLLMResponse(session_id=req.session_id, provider=cfg.get("provider"), model=cfg.get("model"), reply=reply)


@app.get("/api/session/{session_id}")
async def get_session(session_id: str, _user: dict = Depends(get_current_user)):
    cfg = default_manager.get_session(session_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="session not found")
    # Never expose raw API keys, even to authenticated users.
    cfg = dict(cfg)
    for key in ("api_key", "fallback_api_key"):
        if cfg.get(key):
            cfg[key] = mask_secret(cfg[key])
    return cfg


# --------------------------------------------------------------------------- #
# SPA / static
# --------------------------------------------------------------------------- #
@app.get("/")
async def root():
    index_file = os.path.join(PROJECT_ROOT, "frontend", "dist", "client", "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"status": "ok", "service": settings.APP_NAME}


@app.get("/arjun_profile.png")
async def serve_profile_image():
    profile_path = os.path.join(PROJECT_ROOT, "arjun_profile.png")
    if os.path.exists(profile_path):
        return FileResponse(profile_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Profile image not found")


# --------------------------------------------------------------------------- #
# Static frontend mounting (defined after the API routes so APIs win)
# --------------------------------------------------------------------------- #
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_dir = os.path.join(PROJECT_ROOT, "frontend", "dist", "client")

if os.path.exists(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")

    @app.get("/{fallback_path:path}")
    async def serve_frontend(fallback_path: str):
        local_file = os.path.join(frontend_dir, fallback_path)
        if fallback_path and os.path.exists(local_file) and os.path.isfile(local_file):
            return FileResponse(local_file)
        index_file = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return HTMLResponse(
            content="<h3>React Frontend Not Built Yet</h3><p>Please run npm run build inside frontend folder.</p>",
            status_code=404,
        )


# --------------------------------------------------------------------------- #
# Stripe webhook (signature-verified only)
# --------------------------------------------------------------------------- #
from app.db.unified_store import (  # noqa: E402
    store_stripe_transactions,
    strip_unified_transaction,
    update_sync_status,
    write_to_unified_store,
)

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")


def map_stripe_charge(charge: dict) -> dict:
    """Normalizes a Stripe charge object into the unified transaction schema."""
    return strip_unified_transaction(charge, source="stripe")


PAYMENT_EVENTS = {
    "charge.succeeded",
    "charge.captured",
    "charge.refunded",
    "charge.failed",
    "payment_intent.succeeded",
    "payment_intent.payment_failed",
    "payment_intent.canceled",
    "invoice.paid",
    "refund.created",
    "refund.updated",
    "transfer.created",
    "transfer.paid",
    "transfer.failed",
    "payout.created",
    "payout.paid",
    "payout.failed",
}


def _register_stripe_webhook():
    if not STRIPE_SECRET_KEY or not STRIPE_WEBHOOK_SECRET:
        reason = "STRIPE_SECRET_KEY not configured" if not STRIPE_SECRET_KEY else "STRIPE_WEBHOOK_SECRET not configured"
        logger.warning("Stripe webhook disabled: %s.", reason)
        return

    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
    except Exception as e:
        logger.warning("Stripe SDK not available; webhook disabled: %s", e)
        return

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request):
        # Payloads are ONLY accepted with a valid signature. There is no
        # unauthenticated "dev mode" fallback.
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature")
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, STRIPE_WEBHOOK_SECRET
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            raise HTTPException(status_code=400, detail="Invalid signature") from None

        if event["type"] in PAYMENT_EVENTS:
            record = map_stripe_charge(event["data"]["object"])
            inserted = write_to_unified_store([record])
            try:
                store_stripe_transactions([event["data"]["object"]])
            except Exception as e:
                logger.warning("Could not store raw Stripe transaction: %s", e)
            update_sync_status(
                source="stripe",
                status="healthy",
                record_count=inserted,
                last_synced_at=datetime.now(),
            )
        return {"status": "received"}

    logger.info("Stripe webhook registered with signature verification.")


_register_stripe_webhook()