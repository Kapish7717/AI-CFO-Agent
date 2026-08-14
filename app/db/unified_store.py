# ==========================================================
# Unified Transaction Store Helpers
# ==========================================================

import hashlib
import json
import os
from datetime import datetime, timezone

from psycopg2.extras import execute_values

from app.db.pool import get_connection

DATABASE_URL = os.environ.get("DATABASE_URL")

# Canonical unified schema columns (shared by every source - Stripe, excel, etc.)
UNIFIED_COLUMNS = (
    "user_id",
    "external_id",
    "source",
    "transaction_type",
    "direction",
    "amount",
    "currency",
    "transaction_date",
    "description",
    "category",
    "counterparty",
    "status",
    "payment_method",
)


def get_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is required in Supabase-only mode.")
    return get_connection()


def _map_payment_method(payment_method, obj_type):
    pm = (payment_method or "").lower()
    if pm in ("card", "card_present", "contactless"):
        return "card"
    if pm in ("bank_transfer", "ach", "sepa_debit", "bank_account", "transfers", "payout"):
        return "bank_transfer"
    if pm in ("cash",):
        return "cash"
    if obj_type in ("transfer", "payout"):
        return "bank_transfer"
    return pm or "cash"


def _stripe_record(record: dict) -> dict:
    obj_type = (record.get("object") or "charge").lower()
    status_raw = str(record.get("status") or "unknown").lower()
    created_ts = record.get("created") or 0
    try:
        tx_date = datetime.fromtimestamp(float(created_ts), tz=timezone.utc).replace(tzinfo=None)
    except Exception:
        tx_date = None

    if obj_type == "refund":
        transaction_type = "refund"
        direction = "outflow"
        status = "succeeded" if status_raw == "succeeded" else ("failed" if status_raw == "failed" else status_raw)
    elif obj_type in ("transfer", "payout", "dispute"):
        transaction_type = "expense"
        direction = "outflow"
        status = status_raw
    else:  # charge / payment_intent / invoice
        if status_raw == "succeeded":
            transaction_type = "revenue"
            direction = "inflow"
            status = "succeeded"
        else:
            transaction_type = "expense"
            direction = "outflow"
            status = "failed" if status_raw == "failed" else status_raw

    pm_details = record.get("payment_method_details") or {}
    payment_method = _map_payment_method(pm_details.get("type") or record.get("payment_method"), obj_type)
    billing = record.get("billing_details") or {}
    counterparty = (
        billing.get("name")
        or record.get("receipt_email")
        or record.get("customer")
        or "unknown"
    )
    return {
        "user_id": None,
        "external_id": record.get("external_id") or record.get("id") or "unknown",
        "source": "stripe",
        "transaction_type": transaction_type,
        "direction": direction,
        "amount": float(record.get("amount", 0.0)) / 100.0,
        "currency": str(record.get("currency", "USD")).upper(),
        "transaction_date": tx_date,
        "description": record.get("description") or record.get("statement_descriptor") or "",
        "category": transaction_type,
        "counterparty": counterparty,
        "status": status,
        "payment_method": payment_method,
    }


def _generic_record(record: dict, source_name: str) -> dict:
    raw_type = str(record.get("Type") or record.get("transaction_type") or "").lower()
    if raw_type in ("revenue", "income", "sales", "credit", "inflow"):
        transaction_type, direction = "revenue", "inflow"
    elif raw_type in ("refund",):
        transaction_type, direction = "refund", "outflow"
    else:
        transaction_type, direction = "expense", "outflow"
    return {
        "user_id": None,
        "external_id": record.get("external_id") or record.get("id") or "",
        "source": source_name,
        "transaction_type": transaction_type,
        "direction": direction,
        "amount": float(record.get("amount", record.get("Amount", 0.0))),
        "currency": str(record.get("currency", record.get("Currency", "USD"))).upper(),
        "transaction_date": record.get("transaction_date")
        or record.get("date")
        or record.get("Date"),
        "description": record.get("description") or record.get("Description") or "",
        "category": record.get("category") or record.get("Category") or transaction_type,
        "counterparty": record.get("counterparty") or record.get("Entity") or "unknown",
        "status": str(record.get("status") or record.get("Status") or "succeeded").lower(),
        "payment_method": _map_payment_method(
            record.get("payment_method") or record.get("Payment_Method") or "cash", None
        ),
    }


def strip_unified_transaction(record: dict, source: str = None, user_id: int = None) -> dict:
    """Normalizes any external source row into the unified transaction schema.

    New sources can be added by extending the source registry rather than changing
    the database write path.
    """
    if not record:
        return {}

    # Stripe SDK returns StripeObject instances that do not support .get().
    if hasattr(record, "to_dict_recursive"):
        record = record.to_dict_recursive()
    elif hasattr(record, "to_dict"):
        record = record.to_dict()

    source_name = (source or record.get("source") or "unknown").lower()
    if source_name == "stripe":
        normalized = _stripe_record(record)
    else:
        normalized = _generic_record(record, source_name)

    if user_id is not None:
        normalized["user_id"] = user_id
    return normalized


def normalize_unified_records(records: list[dict], user_id: int = None) -> list[dict]:
    return [strip_unified_transaction(r, user_id=user_id) for r in records or []]


def _pick(row: dict, *keys):
    """Case-insensitive lookup across multiple key names."""
    if not row:
        return None
    for k in keys:
        if k in row:
            return row[k]
    low = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        if k.lower() in low:
            return low[k.lower()]
    return None


def _excel_record(user_id: int, row: dict) -> dict:
    """Maps a canonical transactions-table row (Date/Category/Amount/Entity/Type)
    into the unified schema with source='excel'.

    Keys are read case-insensitively so the same mapping works whether the row
    comes from a pandas dataframe (Date/Category/Entity/Amount/Type) or straight
    from the transactions table (date/category/entity/amount/type).
    """
    raw_type = str(_pick(row, "Type", "type", "transaction_type") or "").lower()
    if raw_type in ("revenue", "income", "sales", "credit", "invoice"):
        transaction_type, direction = "revenue", "inflow"
    else:
        transaction_type, direction = "expense", "outflow"

    # Normalize the date to its date part so the same transaction gets the same
    # external_id whether it came from a dataframe (pandas Timestamp) or the DB
    # (datetime), preventing duplicate mirrors.
    raw_date = _pick(row, "Date", "date", "transaction_date")
    date_str = str(raw_date)[:10] if raw_date is not None else ""

    # Canonicalize the amount too: floats ("70258.0") and DB Decimals
    # ("70258.00") must hash identically, otherwise the same row gets a
    # different external_id depending on which path wrote it.
    try:
        amount_str = f"{float(_pick(row, 'Amount', 'amount') or 0.0):.2f}"
    except (TypeError, ValueError):
        amount_str = "0.00"

    key = "|".join([
        date_str,
        raw_type,
        str(_pick(row, "Category", "category") or ""),
        str(_pick(row, "Entity", "entity", "counterparty") or ""),
        amount_str,
    ])
    external_id = hashlib.md5(key.encode("utf-8")).hexdigest()

    return {
        "user_id": user_id,
        "external_id": external_id,
        "source": "excel",
        "transaction_type": transaction_type,
        "direction": direction,
        "amount": float(_pick(row, "Amount", "amount") or 0.0),
        "currency": "USD",
        "transaction_date": raw_date,
        "description": _pick(row, "Description", "description") or _pick(row, "Entity", "entity") or "",
        "category": _pick(row, "Category", "category") or transaction_type,
        "counterparty": _pick(row, "Entity", "entity", "counterparty") or "",
        "status": "succeeded",
        "payment_method": _map_payment_method(
            _pick(row, "Payment_Method", "payment_method") or "cash", None
        ),
    }


def merge_transactions_to_unified(user_id: int, rows: list[dict]) -> dict:
    """Write canonical Excel/sheet transaction rows into unified_transactions
    with source='excel' (idempotent on the content hash)."""
    records = [_excel_record(user_id, r) for r in rows or [] if r]
    if not records:
        return {"inserted": 0, "total": 0}
    inserted = write_to_unified_store(records, user_id=user_id)
    return {"inserted": inserted, "total": len(records)}


def backfill_transactions_to_unified(user_id: int = None) -> dict:
    """Mirror every row already in the user-facing `transactions` table into
    unified_transactions (source='excel') with the correct mapping. This catches
    data ingested before the mirror existed (e.g. uploaded revenue sheets)."""
    from app.db.database import get_all_user_ids, get_user_transactions

    users = [user_id] if user_id else get_all_user_ids()
    results = {}
    total = 0
    for uid in users:
        try:
            rows = get_user_transactions(uid)
            res = merge_transactions_to_unified(uid, rows)
            results[uid] = res
            total += res.get("inserted", 0)
        except Exception as e:
            results[uid] = {"inserted": 0, "error": str(e)}
    return {"inserted": total, "by_user": results}


def update_sync_status(
    source,
    status,
    record_count=None,
    error_message=None,
    last_synced_at=None
):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO sync_status
        (
            source,
            status,
            last_synced_at,
            record_count,
            error_message
        )
        VALUES (%s,%s,%s,%s,%s)

        ON CONFLICT(source)
        DO UPDATE SET
            status = EXCLUDED.status,
            last_synced_at = EXCLUDED.last_synced_at,
            record_count = EXCLUDED.record_count,
            error_message = EXCLUDED.error_message;
        """,
        (
            source,
            status,
            last_synced_at or datetime.now(),
            record_count,
            error_message
        )
    )

    conn.commit()
    cur.close()
    conn.close()


def get_sync_status(source: str):
    """Return the latest sync-status row for ``source`` or None."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source, status, last_synced_at, record_count, error_message "
                "FROM sync_status WHERE source = %s",
                (source,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            col_names = [d.name for d in cur.description]
            return dict(zip(col_names, row, strict=False))
    finally:
        conn.close()


def write_to_unified_store(records, user_id: int = 1):
    if not records:
        return 0

    normalized_records = []
    for r in records or []:
        if r and isinstance(r, dict) and "external_id" in r and "source" in r:
            rec = dict(r)
        else:
            rec = strip_unified_transaction(r)
        if rec.get("user_id") is None:
            rec["user_id"] = user_id
        normalized_records.append(rec)

    if not normalized_records:
        return 0

    conn = get_conn()
    cur = conn.cursor()

    query = """
    INSERT INTO unified_transactions
    (
        user_id,
        external_id,
        source,
        transaction_type,
        direction,
        amount,
        currency,
        transaction_date,
        description,
        category,
        counterparty,
        status,
        payment_method,
        updated_at
    )
    VALUES %s
    ON CONFLICT (external_id, source)
    DO NOTHING
    """

    # Pre-check which (external_id, source) pairs already exist so the inserted
    # count is accurate. `execute_values`' rowcount only reflects the last chunk.
    existing = set()
    by_source: dict[str, list[str]] = {}
    for r in normalized_records:
        by_source.setdefault(r.get("source") or "unknown", []).append(r["external_id"])
    for src, ids in by_source.items():
        cur.execute(
            "SELECT external_id FROM unified_transactions WHERE source = %s AND external_id = ANY(%s)",
            (src, ids),
        )
        for (ext_id,) in cur.fetchall():
            existing.add((src, ext_id))

    to_insert = [
        r for r in normalized_records
        if (r.get("source") or "unknown", r["external_id"]) not in existing
    ]
    if not to_insert:
        cur.close()
        conn.close()
        return 0

    values = [
        (
            r.get("user_id"),
            r.get("external_id"),
            r.get("source"),
            r.get("transaction_type"),
            r.get("direction"),
            r.get("amount"),
            r.get("currency"),
            r.get("transaction_date") or r.get("date"),
            r.get("description"),
            r.get("category"),
            r.get("counterparty"),
            r.get("status"),
            r.get("payment_method"),
            datetime.now(),
        )
        for r in to_insert
    ]

    execute_values(cur, query, values)
    inserted = len(to_insert)

    conn.commit()
    cur.close()
    conn.close()

    return inserted


def store_stripe_transactions(records, user_id: int = 1) -> int:
    """Persist raw Stripe object payloads into the dedicated `stripe_transactions`
    table (Supabase), kept separate from the normalized `unified_transactions`
    view of the same data.

    Accepts Stripe SDK objects or plain dicts (e.g. a Stripe webhook event's
    data.object). Idempotent on the Stripe object id: already-stored objects are
    skipped. Returns the number of new rows inserted.
    """
    if not records:
        return 0

    rows = []
    for rec in records or []:
        if rec is None:
            continue
        if hasattr(rec, "to_dict_recursive"):
            rec = rec.to_dict_recursive()
        elif hasattr(rec, "to_dict"):
            rec = rec.to_dict()
        if not isinstance(rec, dict):
            continue

        obj_id = rec.get("id") or rec.get("external_id")
        if not obj_id:
            continue

        obj_type = (rec.get("object") or "unknown").lower()
        status_raw = str(rec.get("status") or "unknown").lower()
        if obj_type == "charge":
            status = "succeeded" if status_raw in ("succeeded", "captured") else status_raw
        else:
            status = status_raw

        created_ts = rec.get("created") or 0
        try:
            tx_date = datetime.fromtimestamp(float(created_ts), tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            tx_date = None

        billing = rec.get("billing_details") or {}

        rows.append({
            "user_id": user_id,
            "external_id": obj_id,
            "object_type": obj_type,
            "amount": float(rec.get("amount", 0.0)) / 100.0,
            "currency": str(rec.get("currency", "USD")).upper(),
            "transaction_date": tx_date,
            "description": rec.get("description") or rec.get("statement_descriptor") or "",
            "counterparty": (
                billing.get("name")
                or rec.get("receipt_email")
                or rec.get("customer")
                or "unknown"
            ),
            "status": status,
            "raw_payload": json.dumps(rec, default=str),
        })

    if not rows:
        return 0

    conn = get_conn()
    cur = conn.cursor()

    existing = set()
    ids = [r["external_id"] for r in rows]
    cur.execute(
        "SELECT external_id FROM stripe_transactions WHERE external_id = ANY(%s)",
        (ids,),
    )
    for (ext_id,) in cur.fetchall():
        existing.add(ext_id)

    to_insert = [r for r in rows if r["external_id"] not in existing]
    if not to_insert:
        cur.close()
        conn.close()
        return 0

    query = """
    INSERT INTO stripe_transactions
    (
        user_id,
        external_id,
        object_type,
        amount,
        currency,
        transaction_date,
        description,
        counterparty,
        status,
        raw_payload
    )
    VALUES %s
    ON CONFLICT (external_id) DO NOTHING
    """

    values = [
        (
            r["user_id"],
            r["external_id"],
            r["object_type"],
            r["amount"],
            r["currency"],
            r["transaction_date"],
            r["description"],
            r["counterparty"],
            r["status"],
            r["raw_payload"],
        )
        for r in to_insert
    ]
    execute_values(cur, query, values)
    inserted = len(to_insert)

    conn.commit()
    cur.close()
    conn.close()

    return inserted