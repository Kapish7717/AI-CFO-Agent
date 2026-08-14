import logging

from app.db.database import get_all_user_ids, get_user_settings
from app.db.unified_store import (
    store_stripe_transactions,
    strip_unified_transaction,
    update_sync_status,
    write_to_unified_store,
)

logger = logging.getLogger("stripe_sync")


def sync_stripe_charges(user_id: int, api_key: str = None) -> dict:
    """Pull recent Stripe charges for a user and store them normalized.

    Idempotent: charges already in unified_transactions are skipped via the
    (external_id, source) unique constraint. The raw Stripe payloads are also
    mirrored into the dedicated stripe_transactions (Supabase) table.
    """
    if api_key is None:
        settings = get_user_settings(user_id)
        api_key = (settings.get("stripe_secret_key") or "").strip()
    if not api_key:
        return {"success": False, "synced": 0, "error": "No Stripe API key configured for this user"}

    try:
        import stripe
        stripe.api_key = api_key
        charges = stripe.Charge.list(limit=100)
    except Exception as e:
        logger.warning(f"Stripe list failed for user {user_id}: {e}")
        try:
            update_sync_status(source="stripe", status="error", error_message=str(e))
        except Exception:
            pass
        return {"success": False, "synced": 0, "error": str(e)}

    records = [strip_unified_transaction(c, source="stripe", user_id=user_id) for c in charges.data]
    # Keep the raw Stripe payloads so they can be stored in the dedicated
    # stripe_transactions (Supabase) table alongside the normalized view.
    raw_records = list(charges.data)

    # Refunds and money paid out (transfers/payouts) are separate Stripe objects
    # and must be fetched explicitly so outgoing payments land as expenses.
    try:
        refunds = stripe.Refund.list(limit=100)
        records += [strip_unified_transaction(r, source="stripe", user_id=user_id) for r in refunds.data]
        raw_records += list(refunds.data)
    except Exception as e:
        logger.warning(f"Stripe refunds failed for user {user_id}: {e}")
    try:
        transfers = stripe.Transfer.list(limit=100)
        records += [strip_unified_transaction(t, source="stripe", user_id=user_id) for t in transfers.data]
        raw_records += list(transfers.data)
    except Exception as e:
        logger.warning(f"Stripe transfers failed for user {user_id}: {e}")
    try:
        payouts = stripe.Payout.list(limit=100)
        records += [strip_unified_transaction(p, source="stripe", user_id=user_id) for p in payouts.data]
        raw_records += list(payouts.data)
    except Exception as e:
        logger.warning(f"Stripe payouts failed for user {user_id}: {e}")

    inserted = write_to_unified_store(records, user_id=user_id)
    raw_inserted = store_stripe_transactions(raw_records, user_id=user_id)
    update_sync_status(source="stripe", status="healthy", record_count=inserted)
    return {"success": True, "synced": inserted, "raw_stored": raw_inserted, "total": len(records)}


def sync_all_users() -> list[dict]:
    """Sync Stripe charges for every user that has a stored Stripe API key."""
    results = []
    for uid in get_all_user_ids():
        try:
            settings = get_user_settings(uid)
            if (settings.get("stripe_secret_key") or "").strip():
                result = sync_stripe_charges(uid)
                results.append({"user_id": uid, **result})
        except Exception as e:
            logger.warning(f"Stripe sync failed for user {uid}: {e}")
            results.append({"user_id": uid, "success": False, "error": str(e)})
    return results
