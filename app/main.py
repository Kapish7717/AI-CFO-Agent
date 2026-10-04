from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.admin import router as admin_router
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
app.include_router(admin_router)
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


async def _run_scheduled_pipeline(user_id: int):
    """Run one user's CFO pipeline through the MCP supervisor graph.

    The graph is driven by state, not by a prose prompt: the supervisor routes on
    ``trigger`` and the reporting node reads the user's own ``report_months`` and
    ``report_email`` from user_settings. The window is resolved once per run
    inside the supervisor, so the anomaly pass and the PDF cover the same dates.

    Data is read from unified_transactions, which the 60s Stripe loop and the
    Stripe webhook keep current; both write idempotently on
    (external_id, source, user_id), so this run only reads.
    """
    try:
        from app.graph.supervisor import graph

        run_started = time.perf_counter()
        result = await graph.ainvoke(
            {"user_id": user_id, "trigger": "scheduled", "source": "stripe"}
        )
        elapsed_ms = (time.perf_counter() - run_started) * 1000.0

        anomalies = result.get("anomaly_result") or {}
        report = result.get("report") or {}
        logger.info(
            "[SCHEDULER] user=%s took=%.0fms rows=%s anomalies=%s report=%s%s",
            user_id,
            elapsed_ms,
            anomalies.get("rows_analyzed", "?"),
            anomalies.get("anomaly_count", 0),
            report.get("status", "not generated"),
            f" error={report['error']}" if report.get("error") else "",
        )
    except Exception as e:
        logger.error("[SCHEDULER] Pipeline failed for user %s: %s", user_id, e)


#: A run is due if its scheduled minute falls in (last tick, now]. Matching the
#: current minute exactly meant any hiccup - a slow tick, a deploy, a restart -
#: silently cost that user the whole day.
_SCHEDULER_STARTUP_GRACE_MINUTES = 15


def _scheduled_moment(schedule: str, day: datetime) -> datetime | None:
    """Parse a stored ``report_schedule`` into a datetime on *day*.

    Returns None for anything unparseable so a bad value is skipped for that
    user rather than raising inside the loop.
    """
    text = (schedule or "").strip()[:5]
    if not text:
        return None
    try:
        hour, minute = (int(part) for part in text.split(":"))
    except (TypeError, ValueError):
        return None
    try:
        return day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except ValueError:
        return None


async def _scheduled_report_loop():
    """Every 60s, run the CFO pipeline for each user whose report_schedule (HH:MM)
    falls inside the interval just elapsed. Each user runs at most once per day.

    Two deliberate differences from a plain "is it this minute" check:

    * a schedule is matched against the window (last tick, now], so a slow tick
      or a brief restart still runs the report instead of dropping the day;
    * the once-a-day latch lives in user_settings rather than in memory, so a
      deploy cannot produce a duplicate report for someone who already ran.

    A report is generated whether or not it can be emailed; report_email only
    decides whether the delivery step runs.
    """
    # The first pass looks back a short grace period so a report scheduled
    # moments before a deploy still runs. A longer lookback would fire a burst
    # of reports for everyone on a fresh start.
    window_end = datetime.now()
    window_start = window_end - timedelta(minutes=_SCHEDULER_STARTUP_GRACE_MINUTES)
    while True:
        try:
            from app.db.database import (
                get_all_user_ids,
                get_user_settings,
                update_user_settings,
            )

            user_ids = await asyncio.to_thread(get_all_user_ids)
            for user_id in user_ids:
                try:
                    settings_row = await asyncio.to_thread(get_user_settings, user_id)
                    due = _scheduled_moment(settings_row.get("report_schedule"), window_end)
                    if due is None:
                        continue
                    if not (window_start < due <= window_end):
                        continue
                    today = window_end.strftime("%Y-%m-%d")
                    if settings_row.get("report_last_run") == today:
                        continue
                    # Claim the day before dispatching, so a failure here cannot
                    # turn into a retry storm on the next tick.
                    await asyncio.to_thread(
                        update_user_settings, user_id, {"report_last_run": today}
                    )
                    logger.info(
                        "[SCHEDULER] Triggering report for user %s (scheduled %s).",
                        user_id, due.strftime("%H:%M"),
                    )
                    asyncio.create_task(_run_scheduled_pipeline(user_id))
                except Exception as e:
                    logger.error("[SCHEDULER] Error checking user %s: %s", user_id, e)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("[SCHEDULER] Loop error: %s", e)

        await asyncio.sleep(60)
        window_start = window_end
        window_end = datetime.now()


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


def _resolve_users_from_stripe_account(stripe_account_id: str) -> list[int]:
    """Look up all users who have the given Stripe account ID connected."""
    if not stripe_account_id:
        return []
    try:
        from app.db.database import get_connection
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT user_id FROM user_settings WHERE stripe_account_id = %s",
                    (stripe_account_id,),
                )
                return [row["user_id"] for row in cur.fetchall()]
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to resolve users for Stripe account %s: %s", stripe_account_id, e)
        return []


def map_stripe_charge(charge: dict, user_id: int | None = None) -> dict:
    """Normalizes a Stripe charge object into the unified transaction schema."""
    return strip_unified_transaction(charge, source="stripe", user_id=user_id)


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
            # Resolve all users who have this Stripe account connected.
            stripe_account_id = event.get("account")
            user_ids = _resolve_users_from_stripe_account(stripe_account_id)
            if not user_ids:
                logger.warning(
                    "Stripe webhook received for unknown account %s; skipping. "
                    "Background sync will pick up this transaction.",
                    stripe_account_id,
                )
                return {"status": "skipped", "reason": "unknown_account"}

            # Attribute the transaction to all users who share this Stripe account.
            for uid in user_ids:
                record = map_stripe_charge(event["data"]["object"], user_id=uid)
                inserted = write_to_unified_store([record], user_id=uid)
                try:
                    store_stripe_transactions([event["data"]["object"]], user_id=uid)
                except Exception as e:
                    logger.warning("Could not store raw Stripe transaction for user %s: %s", uid, e)
                update_sync_status(
                    source="stripe",
                    status="healthy",
                    record_count=inserted,
                    last_synced_at=datetime.now(),
                )
        return {"status": "received"}

    logger.info("Stripe webhook registered with signature verification.")


_register_stripe_webhook()