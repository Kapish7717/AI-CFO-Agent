# ==========================================================
# supabase-mcp: org scoping helpers
# ==========================================================

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

from app.db.database import get_domain_user_ids, get_user_by_id


def resolve_org_scope(user_id: int) -> list[int]:
    """Validate that *user_id* refers to a real user and return the full set of
    user ids in the same company domain (the multi-tenant scope of every read).

    Mirrors ``get_domain_user_ids``: a user with no domain is isolated to
    ``[user_id]``. Raises ``ValueError`` when the user does not exist.
    """
    if user_id is None:
        raise ValueError("user_id is required")
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError(f"No user found with id {user_id}")
    return get_domain_user_ids(user_id)


def jsonable(value):
    """Convert DB values (rows, datetimes, Decimals, bytes) to JSON-safe
    primitives so MCP tool results serialize cleanly over the transport.
    """
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, set):
        return sorted(jsonable(v) for v in value)
    return value