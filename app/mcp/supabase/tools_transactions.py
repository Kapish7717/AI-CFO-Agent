# ==========================================================
# supabase-mcp: write tools (org-scoped)
# ==========================================================

from __future__ import annotations

import asyncio

from app.db.unified_store import (
    store_stripe_transactions,
    strip_unified_transaction,
    update_sync_status,
    write_to_unified_store,
)
from app.mcp.supabase.org import resolve_org_scope


def _write_transactions(
    user_id: int, source: str, transactions: list[dict]
) -> dict:
    resolve_org_scope(user_id)
    if not transactions:
        return {"inserted": 0, "total": 0}

    normalized = []
    for rec in transactions:
        row = strip_unified_transaction(rec, source=source, user_id=user_id)
        if row:
            normalized.append(row)

    inserted = write_to_unified_store(normalized, user_id=user_id)
    return {"inserted": inserted, "total": len(normalized)}


async def write_transactions(
    user_id: int, source: str, transactions: list[dict]
) -> dict:
    """Upsert transactions into unified_transactions on behalf of ``user_id``.

    ``source`` names the data origin (e.g. stripe, excel) and any record that
    isn't already unified-shaped is normalized via the same mapper the webhook
    and upload pipeline use (Stripe cents -> dollars, direction/type mapping).
    Idempotent on (external_id, source, user_id). Returns inserted/total.
    """
    return await asyncio.to_thread(_write_transactions, user_id, source, transactions)


def _write_stripe_transactions(user_id: int, records: list[dict]) -> dict:
    resolve_org_scope(user_id)
    if not records:
        return {"inserted": 0, "total": 0}
    inserted = store_stripe_transactions(records, user_id=user_id)
    return {"inserted": inserted, "total": len(records)}


async def write_stripe_transactions(user_id: int, records: list[dict]) -> dict:
    """Persist raw Stripe object payloads into stripe_transactions on behalf of
    ``user_id`` (org-scoped). Idempotent on the Stripe object id; accepts the
    raw dicts returned by stripe-mcp fetch tools. Returns inserted/total.
    """
    return await asyncio.to_thread(_write_stripe_transactions, user_id, records)


def _mark_sync_status(
    user_id: int,
    source: str,
    status: str,
    record_count: int | None = None,
    error_message: str | None = None,
) -> dict:
    resolve_org_scope(user_id)
    update_sync_status(
        source=source,
        status=status,
        record_count=record_count,
        error_message=error_message,
    )
    payload = {
        "source": source,
        "status": status,
        "record_count": record_count,
        "error_message": error_message,
    }
    return {k: v for k, v in payload.items() if v is not None}


async def mark_sync_status(
    user_id: int,
    source: str,
    status: str,
    record_count: int | None = None,
    error_message: str | None = None,
) -> dict:
    """Persist a sync-status entry for ``source`` (e.g. healthy/error).

    ``status``: healthy/error/disconnected. ``record_count``: rows synced last
    run; ``error_message``: details on failure. Caller must belong to the org.
    """
    return await asyncio.to_thread(
        _mark_sync_status,
        user_id,
        source,
        status,
        record_count,
        error_message,
    )