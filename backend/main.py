from __future__ import annotations

import os
import sys
import json
import logging
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, Any

# Load environment variables (.env) before importing any modules that read them.
load_dotenv()

# Import default managers / config helpers
from backend.services.session_manager import default_manager
from backend.services.llm_factory import create_llm, generate_text

# Import individual routers from backend/api
from backend.api.auth import router as auth_router
from backend.api.chat import router as chat_router
from backend.api.dashboard import router as dashboard_router
from backend.api.forecast import router as forecast_router
from backend.api.anomaly import router as anomaly_router
from backend.api.integrations import router as integrations_router
from backend.api.providers import router as providers_router
from backend.api.report import router as report_router
from backend.api.settings import router as settings_router
from backend.api.agent import router as agent_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("cfo_backend.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("cfo_backend_api")
logger.info("FastAPI Backend Server logging initialized.")

app = FastAPI(title="AI CFO Agent Backend")

# Allow requests from all origins (CORS) for development/production flexibility.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DB on startup
@app.on_event("startup")
def startup_event():
    from db.database import init_db
    try:
        logger.info("Initializing database on startup...")
        init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization failed during startup: {e}", exc_info=True)
        sys.stderr.write(f"[DB STARTUP ERROR] {e}\n")

    # Start the scheduled-report background loop (best effort; failures are logged).
    try:
        import asyncio
        asyncio.get_event_loop().create_task(_scheduled_report_loop())
        logger.info("Scheduled report loop started.")
    except Exception as e:
        logger.error(f"Could not start scheduled report loop: {e}")

    # Start the Stripe periodic sync loop so new charges reach unified_transactions
    # even when no webhook is configured.
    try:
        import asyncio
        asyncio.get_event_loop().create_task(_stripe_sync_loop())
        logger.info("Stripe sync loop started.")
    except Exception as e:
        logger.error(f"Could not start Stripe sync loop: {e}")


_report_last_run: dict = {}


async def _run_scheduled_pipeline(user_id: int):
    """Run one user's CFO pipeline in a detached background task."""
    try:
        from backend.services.agent_runner import run_cfo_pipeline
        result = await run_cfo_pipeline(user_id=user_id)
        logger.info(f"[SCHEDULER] Pipeline result for user {user_id}: {result.get('message', 'done')}")
    except Exception as e:
        logger.error(f"[SCHEDULER] Pipeline failed for user {user_id}: {e}")


async def _scheduled_report_loop():
    """Every 60s, run the CFO pipeline for users whose report_schedule (HH:MM)
    matches the current time. Each user runs at most once per day."""
    from datetime import datetime
    import asyncio

    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            hhmm = now.strftime("%H:%M")

            from db.database import get_all_user_ids, get_user_settings
            for user_id in get_all_user_ids():
                try:
                    settings = get_user_settings(user_id)
                    schedule = (settings.get("report_schedule") or "").strip()
                    email = (settings.get("report_email") or "").strip()
                    if not schedule or not email:
                        continue
                    if schedule[:5] != hhmm:
                        continue
                    if _report_last_run.get(user_id) == today:
                        continue
                    _report_last_run[user_id] = today
                    logger.info(f"[SCHEDULER] Triggering report for user {user_id} at {hhmm}.")
                    asyncio.get_event_loop().create_task(_run_scheduled_pipeline(user_id))
                except Exception as e:
                    logger.error(f"[SCHEDULER] Error checking user {user_id}: {e}")
        except Exception as e:
            logger.error(f"[SCHEDULER] Loop error: {e}")

        await asyncio.sleep(60)


async def _stripe_sync_loop():
    """Every 60s, pull new Stripe charges for all connected users.

    This guarantees new Stripe transactions reach unified_transactions even when
    no webhook endpoint is configured. Idempotent thanks to the (external_id,
    source) unique constraint.
    """
    import asyncio

    while True:
        try:
            from backend.services.stripe_sync import sync_all_users
            await asyncio.to_thread(sync_all_users)
        except Exception as e:
            logger.error(f"[STRIPE SYNC] Loop error: {e}")
        await asyncio.sleep(60)

# Include routers
# Note: since decorators in routers define their exact absolute paths (e.g., /api/auth/login, /stream),
# we include them without any additional prefix.
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


class TestLLMRequest(BaseModel):
    session_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    prompt: str
    save_session: bool = False


class TestLLMResponse(BaseModel):
    session_id: Optional[str]
    provider: Optional[str]
    model: Optional[str]
    reply: str


@app.post("/api/test-llm", response_model=TestLLMResponse)
async def test_llm(req: TestLLMRequest):
    # Try to load existing session
    cfg = None
    if req.session_id:
        cfg = default_manager.get_session(req.session_id)

    if cfg is None:
        if not (req.provider and req.api_key):
            raise HTTPException(status_code=400, detail="No session found and provider/api_key not provided")
        cfg = {"provider": req.provider, "model": req.model, "api_key": req.api_key}

    # Optionally persist session
    if req.save_session and req.session_id:
        default_manager.set_session(req.session_id, cfg)

    # Create LLM and generate
    try:
        llm = create_llm(provider=cfg.get("provider"), model=cfg.get("model"), api_key=cfg.get("api_key"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    reply = await generate_text(llm, req.prompt)

    return TestLLMResponse(session_id=req.session_id, provider=cfg.get("provider"), model=cfg.get("model"), reply=reply)


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    cfg = default_manager.get_session(session_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="session not found")
    return cfg


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/")
async def root():
    frontend_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "fin-genie-os", "dist", "client"
    )
    index_file = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"status": "ok", "service": "AI CFO Agent Backend"}


@app.get("/arjun_profile.png")
async def serve_profile_image():
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    profile_path = os.path.join(PROJECT_ROOT, "arjun_profile.png")
    if os.path.exists(profile_path):
        return FileResponse(profile_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Profile image not found")


# Serve React static files (fin-genie-os/dist) if built
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
frontend_dir = os.path.join(PROJECT_ROOT, "fin-genie-os", "dist", "client")

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
        return HTMLResponse(content="<h3>React Frontend Not Built Yet</h3><p>Please run npm run build inside fin-genie-os folder.</p>", status_code=404)

# Stripe webhook (optional). Enabled when STRIPE_SECRET_KEY is configured.
# Whenever a Stripe transaction event arrives, the charge/payment is normalized
# into the unified transaction store automatically.
# STRIPE_WEBHOOK_SECRET (from Stripe -> Developers -> Webhooks) is used only to
# verify the request signature when provided; without it the webhook still works
# in dev mode but skips signature verification.
from db.unified_store import strip_unified_transaction, write_to_unified_store, update_sync_status

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

def map_stripe_charge(charge: dict) -> dict:
    """Normalizes a Stripe charge object into the unified transaction schema."""
    return strip_unified_transaction(charge, source="stripe")

# Stripe events that represent a transaction and should be persisted.
# Incoming payments (charges/payment intents) record as revenue when they
# succeed; money going out (refunds, transfers, payouts) records as expense.
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

if STRIPE_SECRET_KEY:
    try:
        import stripe
        stripe.api_key = STRIPE_SECRET_KEY
    except Exception as e:
        logger.warning(f"Stripe SDK not available; webhook disabled: {e}")
        stripe = None

    if stripe is not None:

        @app.post("/webhooks/stripe")
        async def stripe_webhook(request: Request):
            payload = await request.body()
            sig_header = request.headers.get("stripe-signature")

            if STRIPE_WEBHOOK_SECRET:
                try:
                    event = stripe.Webhook.construct_event(
                        payload, sig_header, STRIPE_WEBHOOK_SECRET
                    )
                except (ValueError, stripe.error.SignatureVerificationError):
                    raise HTTPException(status_code=400, detail="Invalid signature")
            else:
                # Dev mode: no signing secret configured, so accept as-is.
                logger.warning(
                    "STRIPE_WEBHOOK_SECRET not configured; accepting webhook "
                    "without signature verification (dev mode)."
                )
                event = json.loads(payload)

            if event["type"] in PAYMENT_EVENTS:
                record = map_stripe_charge(event["data"]["object"])
                inserted = write_to_unified_store([record])
                update_sync_status(
                    source="stripe",
                    status="healthy",
                    record_count=inserted,
                    last_synced_at=datetime.now(),
                )

            return {"status": "received"}
    else:
        logger.info("Stripe webhook disabled: Stripe SDK unavailable.")
else:
    logger.info("Stripe webhook disabled: STRIPE_SECRET_KEY not configured.")