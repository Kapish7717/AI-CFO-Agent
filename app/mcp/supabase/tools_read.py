# ==========================================================
# supabase-mcp: read tools (org-scoped)
# ==========================================================

from __future__ import annotations

import asyncio

from app.db.database import get_connection
from app.db.unified_store import get_sync_status as _store_get_sync_status
from app.mcp.supabase.org import jsonable, resolve_org_scope

# Canonical unified_transactions projection (every source shares this shape).
_UNIFIED_PROJECTION = (
    "id, user_id, external_id, source, transaction_type, direction, amount, "
    "currency, transaction_date, description, category, counterparty, status, "
    "payment_method"
)


def _fetch_transactions(
    user_ids: list[int], clauses: list[tuple[str, object]], limit: int
) -> list[dict]:
    """Run a FIXED-column query against unified_transactions scoped to
    ``user_ids`` with optional ``AND col op %s`` clauses (param etized).

    Ordered newest-first so that ``limit`` keeps the most recent rows rather
    than the oldest; callers analyzing recency (anomaly detection, cashflow
    trend) depend on this.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            placeholders = ", ".join(["%s"] * len(user_ids))
            sql = (
                f"SELECT {_UNIFIED_PROJECTION} FROM unified_transactions "
                f"WHERE user_id IN ({placeholders})"
            )
            params: list[object] = list(user_ids)
            for clause, val in clauses:
                sql += f" AND {clause} %s"
                params.append(val)
            sql += " ORDER BY transaction_date DESC LIMIT %s"
            params.append(limit)
            cur.execute(sql, tuple(params))
            return cur.fetchall()
    finally:
        conn.close()


def _read_org_transactions(
    user_id: int,
    limit: int,
    *,
    source: str | None = None,
    category: str | None = None,
    direction: str | None = None,
    transaction_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    user_ids = resolve_org_scope(user_id)
    clauses: list[tuple[str, object]] = []
    for col, op, val in (
        ("source", "=", source),
        ("category", "=", category),
        ("direction", "=", direction),
        ("transaction_type", "=", transaction_type),
        ("transaction_date", ">=", start_date),
        ("transaction_date", "<=", end_date),
    ):
        if val is not None:
            clauses.append((f"{col} {op}", val))
    rows = _fetch_transactions(user_ids, clauses, limit)
    return [jsonable(r) for r in rows]


async def list_transactions(
    user_id: int,
    source: str | None = None,
    category: str | None = None,
    direction: str | None = None,
    transaction_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """List org-scoped transactions from unified_transactions.

    The caller's company domain (all users sharing the same email domain) is
    always included. Optional filters: source (stripe/excel), category,
    direction (inflow/outflow), transaction_type (revenue/expense/refund) and
    ISO date bounds for transaction_date. Returns newest-first ordering by
    transaction_date, limited to ``limit`` rows (default 1000), so a limit
    smaller than the org's history keeps the most recent transactions.
    """
    return await asyncio.to_thread(
        _read_org_transactions,
        user_id,
        limit,
        source=source,
        category=category,
        direction=direction,
        transaction_type=transaction_type,
        start_date=start_date,
        end_date=end_date,
    )


def _read_stripe_transactions(user_id: int, limit: int) -> list[dict]:
    user_ids = resolve_org_scope(user_id)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            placeholders = ", ".join(["%s"] * len(user_ids))
            cur.execute(
                f"SELECT id, user_id, external_id, object_type, amount, currency, "
                f"transaction_date, description, counterparty, status, raw_payload "
                f"FROM stripe_transactions "
                f"WHERE user_id IN ({placeholders}) "
                f"ORDER BY transaction_date DESC LIMIT %s",
                (*user_ids, limit),
            )
            return cur.fetchall()
    finally:
        conn.close()


async def list_stripe_transactions(user_id: int, limit: int = 1000) -> list[dict]:
    """List raw Stripe payloads stored in stripe_transactions (org-scoped).

    ``raw_payload`` is the full Stripe object as received (charges, refunds,
    transfers, payouts, disputes). Prefer unified list_transactions for
    analytics; use this for raw-object debugging.
    """
    rows = await asyncio.to_thread(_read_stripe_transactions, user_id, limit)
    return [jsonable(r) for r in rows]


def _read_sync_status(user_id: int, source: str) -> dict | None:
    resolve_org_scope(user_id)
    row = _store_get_sync_status(source)
    return jsonable(row) if row else None


async def get_sync_status(user_id: int, source: str) -> dict | None:
    """Return the latest sync-status entry for ``source`` (e.g. stripe).

    Note: the sync_status table is keyed per source, not per user; ``user_id``
    authorizes the caller (must belong to the org) but the status row is
    shared, matching the current API behavior.
    """
    return await asyncio.to_thread(_read_sync_status, user_id, source)