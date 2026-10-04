# ==========================================================
# supabase-mcp: read tools (org-scoped)
# ==========================================================

from __future__ import annotations

import asyncio
import datetime

from app.db.database import get_connection
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


def _validate_iso_date(label: str, value: str | None) -> None:
    """Reject a malformed date bound instead of letting it match nothing.

    A typo like "2026-13-45" is a perfectly valid string to parameterize, so the
    query runs and returns zero rows, which reads as "this user has no
    transactions" rather than "this filter is wrong".
    """
    if value is None:
        return
    try:
        datetime.date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc


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
    _validate_iso_date("start_date", start_date)
    _validate_iso_date("end_date", end_date)
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