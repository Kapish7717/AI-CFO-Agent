"""Upstash Redis cache with fail-open semantics.

Caching is an optimisation, never a dependency: if Redis is unconfigured,
slow or down, every helper here returns None / no-ops and the caller simply
recomputes. Values are JSON blobs owned by the caller.

Credentials come from UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN.
Every cache hit costs one HTTP round trip, so the Upstash region should be
close to the API host (Render runs in Oregon -> us-west-2).
"""

from __future__ import annotations

import json
import logging

from app.core.config import get_settings

logger = logging.getLogger("cfo.cache")

_client = None
_unconfigured = False

def get_redis():
    global _client, _unconfigured
    if _client is not None:
        return _client
    if _unconfigured:
        return None

    settings = get_settings()

    if not settings.UPSTASH_REDIS_REST_URL or not settings.UPSTASH_REDIS_REST_TOKEN:
        _unconfigured = True
        logger.info("Redis cache disabled : UPSTASH_REDIS_REST_URL/TOKEN not set.")
        return None

    try:
        from upstash_redis import Redis
        # rest_retries=0: the SDK's default waits ~3s and retries, which would
        # turn a cache outage into a 3s stall on every dashboard load. Fail fast.
        _client = Redis(
            url=settings.UPSTASH_REDIS_REST_URL,
            token=settings.UPSTASH_REDIS_REST_TOKEN,
            rest_retries=0,
            allow_telemetry=False,
        )

        return _client
    except Exception as exc :
        _unconfigured = True
        logger.warning("Redis client init failed; caching disabled: %s", exc)
        return None


def cache_get(key: str):
    """Decoded value, or None on miss / unavailable / error."""
    client = get_redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception as exc:
        logger.warning("Redis GET %s failed (treated as miss): %s", key, exc)
        return None
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw  # SDK already decoded the JSON for us
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None  # not JSON we stored — treat as a miss

def cache_set(key: str, value, ttl_seconds: int) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        client.set(key, json.dumps(value), ex=int(ttl_seconds))
    except Exception as exc:
        logger.warning("Redis SET %s failed (ignored): %s", key, exc)


def cache_delete(key: str) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception as exc:
        logger.warning("Redis DEL %s failed (ignored): %s", key, exc)