'''Backend AI Service Layer

This module provides high‑level helper functions that the FastAPI route handlers
can call to interact with the various LangGraph agents defined in the
`backend.graph` package. It abstracts away LLM creation, session handling and
agent execution so that the API layer stays thin and focused on request/response
concerns.
'''

from __future__ import annotations

from typing import Any

from app.services.llm_factory import create_llm_with_fallback, generate_text
from app.services.session_manager import default_manager as session_manager

# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def get_session_config(session_id: str) -> dict[str, Any]:
    """Retrieve stored configuration for a user session.

    Raises
    ------
    ValueError
        If the session does not exist.
    """
    cfg = session_manager.get_session(session_id)
    if cfg is None:
        raise ValueError(f"Session '{session_id}' not found")
    return cfg

# ---------------------------------------------------------------------------
# Provider / Model discovery
# ---------------------------------------------------------------------------

def list_providers() -> list[str]:
    """Return a list of supported LLM providers.

    The factory knows which providers are implemented via optional imports.
    """
    providers: list[str] = []
    try:
        from app.services.llm_factory import ChatOpenAI
        if ChatOpenAI is not None:
            providers.append("openai")
    except Exception:
        pass
    try:
        from app.services.llm_factory import ChatGroq
        if ChatGroq is not None:
            providers.append("groq")
    except Exception:
        pass
    try:
        from app.services.llm_factory import ChatGoogleGenerativeAI
        if ChatGoogleGenerativeAI is not None:
            providers.append("gemini")
    except Exception:
        pass
    try:
        from app.services.llm_factory import ChatAnthropic
        if ChatAnthropic is not None:
            providers.append("anthropic")
    except Exception:
        pass
    providers.append("mock")
    return providers


def _fetch_live_models(provider: str, api_key: str | None) -> list[str] | None:
    """Try to fetch the provider's current model list using the user's API key.

    Returns ``None`` when no key was provided or the request fails so the caller
    can fall back to the static list.
    """
    if not api_key:
        return None
    api_key = api_key.strip()
    if not api_key:
        return None

    import requests

    endpoints = {
        "groq": ("https://api.groq.com/openai/v1/models", "Bearer"),
        "openai": ("https://api.openai.com/v1/models", "Bearer"),
        "openrouter": ("https://openrouter.ai/api/v1/models", "Bearer"),
        "gemini": ("https://generativelanguage.googleapis.com/v1beta/models", "none"),
        "google": ("https://generativelanguage.googleapis.com/v1beta/models", "none"),
        "google_genai": ("https://generativelanguage.googleapis.com/v1beta/models", "none"),
    }
    if provider not in endpoints:
        return None

    url, auth = endpoints[provider]
    try:
        if auth == "Bearer":
            headers = {"Authorization": f"Bearer {api_key}"}
            resp = requests.get(url, headers=headers, timeout=10)
        else:
            resp = requests.get(url, params={"key": api_key}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json().get("data", [])
        if provider in ("gemini", "google", "google_genai"):
            models = [m.get("name", "") for m in data]
            models = [m.split("/")[-1] for m in models if m]
        else:
            models = [m.get("id", "") for m in data if isinstance(m, dict)]
        models = [m for m in models if m]
        if models:
            return sorted(set(models))
    except Exception:
        return None
    return None


def list_models(provider: str, api_key: str | None = None) -> list[str]:
    """Return a list of model identifiers for the given provider.

    When ``api_key`` is provided, the provider's live model list is fetched from
    its API; otherwise a static curated list is returned.
    """
    p = provider.lower()
    live = _fetch_live_models(p, api_key)
    if live:
        return live
    if p == "openai":
        return ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o1", "o1-mini", "gpt-3.5-turbo"]
    if p == "groq":
        return ["llama-3.3-70b-versatile", "llama-3.1-70b-versatile", "mixtral-8x7b-32768"]
    if p in {"gemini", "google", "google_genai"}:
        return ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"]
    if p in {"anthropic", "claude"}:
        return ["claude-sonnet-4-5", "claude-opus-4-0", "claude-haiku-4-5", "claude-3-opus-20240229", "claude-3-sonnet-20240229"]
    if p in {"openrouter",}:
        return ["openai/gpt-4o", "anthropic/claude-sonnet-4", "meta-llama/llama-3.3-70b-instruct", "google/gemini-2.5-flash"]
    if p == "mock":
        return ["mock-model"]
    raise ValueError(f"Unsupported provider '{provider}'")

# ---------------------------------------------------------------------------
# Core interaction – chat
# ---------------------------------------------------------------------------

async def chat(session_id: str, messages: list[dict[str, str]]) -> str:
    """Send a list of messages to the configured LLM and return the reply.

    Parameters
    ----------
    session_id : str
        Identifier of the user session (managed by SessionManager).
    messages : List[Dict[str, str]]
        Each dict contains ``role`` (``user``/``assistant``) and ``content``.
    """
    cfg = get_session_config(session_id)
    llm = create_llm_with_fallback(cfg)
    # Simple concatenation of messages for the generic ``generate_text`` helper.
    prompt = "\n".join(f"{m['role'].capitalize()}: {m['content']}" for m in messages)
    return await generate_text(llm, prompt)

# ---------------------------------------------------------------------------
# Report generation (placeholder)
# ---------------------------------------------------------------------------

async def generate_report(session_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Run the ReportAgent for the given session.

    This is a minimal stub demonstrating the expected signature. The real
    implementation would import ``backend.graph.report_agent`` and call its ``run``
    method.
    """
    ReportAgent = _load_agent("backend.graph.report_agent", "ReportAgent")
    cfg = get_session_config(session_id)
    llm = create_llm_with_fallback(cfg)
    agent = ReportAgent(llm=llm, config=cfg)
    return await agent.run(data)

# ---------------------------------------------------------------------------
# Forecast (placeholder)
# ---------------------------------------------------------------------------

async def forecast(session_id: str, horizon: int, historic: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run the ForecastAgent.

    Parameters
    ----------
    horizon : int
        Number of future periods to predict.
    historic : List[Dict[str, Any]]
        Past financial records.
    """
    ForecastAgent = _load_agent("backend.graph.forecast_agent", "ForecastAgent")
    cfg = get_session_config(session_id)
    llm = create_llm_with_fallback(cfg)
    agent = ForecastAgent(llm=llm, config=cfg)
    return await agent.run(horizon=horizon, historic=historic)

# ---------------------------------------------------------------------------
# Anomaly detection (placeholder)
# ---------------------------------------------------------------------------

async def detect_anomalies(session_id: str, transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run the FraudAgent / anomaly detection pipeline."""
    FraudAgent = _load_agent("backend.graph.fraud_agent", "FraudAgent")
    cfg = get_session_config(session_id)
    llm = create_llm_with_fallback(cfg)
    agent = FraudAgent(llm=llm, config=cfg)
    return await agent.run(transactions)

# ---------------------------------------------------------------------------
# Utility – dynamic import
# ---------------------------------------------------------------------------

def _load_agent(module_name: str, class_name: str) -> Any:
    """Dynamically import an agent class.

    Lazy import avoids circular dependencies and optional‑dependency import errors.
    """
    import importlib
    module = importlib.import_module(module_name)
    return getattr(module, class_name)

# Exported names for ``from app.services.ai_service import *``

__all__ = [
    "list_providers",
    "list_models",
    "chat",
    "generate_report",
    "forecast",
    "detect_anomalies",
]
