"""Centralized, validated application configuration.

All runtime settings are defined here as a single pydantic-settings model read
from the environment (and ``.env``). Every module should pull values from
``get_settings()`` instead of sprinkling ``os.environ`` reads across the codebase.

Security posture:
  * ``DATABASE_URL`` is required in every environment.
  * ``JWT_SECRET_KEY`` must be provided in production; in development an
    ephemeral key is generated on startup (tokens are invalidated on restart).
"""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("cfo.config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application -------------------------------------------------------
    APP_NAME: str = "AI CFO Agent Backend"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    # --- Database ----------------------------------------------------------
    DATABASE_URL: str = ""
    DB_POOL_MIN: int = 1
    DB_POOL_MAX: int = 10
    DB_CONNECT_TIMEOUT: int = 10

    # --- Authentication (JWT) ----------------------------------------------
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day

    # --- CORS ---------------------------------------------------------------
    # Comma-separated list of allowed origins, e.g. "https://app.example.com"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:7860"

    # --- Integrations --------------------------------------------------------
    GROQ_API_KEY: str = ""
    JINA_API_KEY: str = ""
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    GOOGLE_CREDENTIALS_JSON: str = ""

    # --- File uploads --------------------------------------------------------
    MAX_UPLOAD_MB: int = 25
    ALLOWED_UPLOAD_EXTENSIONS: str = ".csv,.xlsx,.xls"

    # --- Dashboard ------------------------------------------------------------
    # Seed "cash on hand" used when computing the dashboard cash balance. In a
    # self-serve deployment this should be tracked from real source accounts.
    CASH_BASE_AMOUNT: float = 1_750_000.0

    # --- Feature flags ---------------------------------------------------------
    ALLOW_MODEL_FALLBACK: bool = False
    # Seed a default demo user (arjun@cfo.com) at first startup. Keep disabled in
    # production — the default password is public knowledge.
    SEED_DEFAULT_USER: bool = False

    @field_validator("CORS_ORIGINS")
    @classmethod
    def _split_origins(cls, v: str) -> str:
        if v and not all(o.startswith(("http://", "https://")) for o in v.split(",") if o.strip()):
            raise ValueError("CORS_ORIGINS must be a comma-separated list of http(s) origins")
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_upload_extensions(self) -> set[str]:
        return {e.strip().lower() for e in self.ALLOWED_UPLOAD_EXTENSIONS.split(",") if e.strip()}

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.lower() in {"production", "prod"}

    @property
    def jwt_secret(self) -> str:
        if self.JWT_SECRET_KEY:
            return self.JWT_SECRET_KEY
        if self.is_production:
            raise RuntimeError(
                "JWT_SECRET_KEY must be set when APP_ENV is 'production'."
            )
        # Development-only: derive a stable-per-deployment key so the server
        # boots and tokens survive restarts, but loudly flag it as insecure.
        derived = hashlib.sha256(
            f"{self.APP_NAME}:{self.DATABASE_URL}".encode()
        ).hexdigest()
        logger.warning(
            "JWT_SECRET_KEY is not set; using an auto-generated DEVELOPMENT key "
            "(NOT safe for production). Set JWT_SECRET_KEY to a random value."
        )
        return derived

    def validate_production(self) -> None:
        """Fail fast on a misconfigured production deployment."""
        missing = []
        if not self.DATABASE_URL:
            missing.append("DATABASE_URL")
        if self.is_production and not self.JWT_SECRET_KEY:
            missing.append("JWT_SECRET_KEY")
        if missing:
            raise RuntimeError(
                f"Missing required configuration for APP_ENV={self.APP_ENV}: {', '.join(missing)}"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()