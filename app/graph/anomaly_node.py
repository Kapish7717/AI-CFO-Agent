# ==========================================================
# Anomaly node: supabase-mcp read -> existing CFO detectors
# ==========================================================
# Deterministic (no LLM). Reads org-scoped rows from unified_transactions via
# the supabase-mcp ``list_transactions`` tool, reshapes them into the column
# contract that app/tools/anomaly_detection.py expects, and runs the same
# detectors the legacy API path uses. Writes anomaly_result / anomalies /
# anomaly_flags; the conditional edge reads anomaly_flags to route reporting.

import asyncio

import pandas as pd

from app.graph.ingestion_node import _as_records, _call, _ok_records
from app.graph.mcp_client import get_pipeline_tools
from app.graph.state import PipelineState
from app.tools.anomaly_detection import detect_all_anomalies

# Detector boolean column -> the flag name exposed in state.
_SIGNAL_FLAGS = {
    "Anomaly_ZScore": "zscore",
    "Anomaly_IQR": "iqr",
    "Anomaly_RuleBased": "rule_based",
    "Is_Budget_Breach": "budget_breach",
}

# unified_transactions stores lowercase types; the detectors (and in
# particular detect_budget_breaches, which filters Type == 'Expense') expect
# the capitalized form, so normalize on the way in.
_TYPE_LABELS = {"expense": "Expense", "revenue": "Revenue", "refund": "Refund"}


def _to_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _entity(row: dict) -> str:
    """Pick the best available grouping key for duplicate/MoM rules.

    Falls back to external_id rather than a constant, so rows with no
    counterparty are not all collapsed into one duplicate group.
    """
    for key in ("counterparty", "description", "external_id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return "unknown"


def _to_detector_frame(rows: list[dict]) -> pd.DataFrame:
    """Reshape unified rows into the detectors' column contract."""
    frame = pd.DataFrame(
        [
            {
                "ExternalID": row.get("external_id"),
                "Amount": _to_float(row.get("amount")),
                "Date": row.get("transaction_date"),
                "Entity": _entity(row),
                "Type": _TYPE_LABELS.get(str(row.get("transaction_type") or "").lower()),
                "Category": row.get("category"),
                "Source": row.get("source"),
            }
            for row in rows
        ]
    )
    frame["Amount"] = pd.to_numeric(frame["Amount"], errors="coerce")
    return frame


def load_budget_limits(user_id: int) -> dict:
    """Build per-category limits from user settings, mirroring the legacy
    detect_financial_anomalies tool."""
    from app.db.database import get_user_settings
    from app.services.budget_breaches import CATEGORY_MAP

    try:
        settings = get_user_settings(user_id) or {}
    except Exception:  # noqa: BLE001 - budget config must never break analysis
        return {}
    limits: dict[str, float] = {}
    for field, category in CATEGORY_MAP.items():
        try:
            limit = float(settings.get(field)) if settings.get(field) else 0.0
        except (TypeError, ValueError):
            limit = 0.0
        if limit > 0:
            limits[category] = limit
    return limits


def _is_analyzable(row: dict) -> bool:
    """Reject rows the detectors would misread.

    Legacy Excel ingestion left rows with no amount (or 0) and an epoch date.
    The duplicate and large-amount rules treat those as identical records, so
    they flood the report with false positives. They are skipped here rather
    than deleted; the caller reports how many were excluded.
    """
    amount = _to_float(row.get("amount"))
    if amount is None or amount == 0:
        return False
    date = row.get("transaction_date")
    if not date:
        return False
    return not pd.isna(pd.to_datetime(date, errors="coerce"))


def _to_anomaly_records(analyzed: pd.DataFrame) -> list[dict]:
    """Reduce the analyzed frame to JSON-safe anomaly rows."""
    records: list[dict] = []
    for _, row in analyzed.iterrows():
        amount = row.get("Amount")
        date = row.get("Date")
        records.append(
            {
                "external_id": row.get("ExternalID"),
                "amount": None if pd.isna(amount) else float(amount),
                "transaction_date": None if pd.isna(date) else pd.Timestamp(date).isoformat(),
                "transaction_type": row.get("Type"),
                "category": None if pd.isna(row.get("Category")) else row.get("Category"),
                "entity": row.get("Entity"),
                "severity": row.get("Severity"),
                "signals": [
                    flag for column, flag in _SIGNAL_FLAGS.items() if bool(row.get(column))
                ],
            }
        )
    return records


def _fired_signals(analyzed: pd.DataFrame) -> list[str]:
    return sorted({flag for column, flag in _SIGNAL_FLAGS.items() if bool(analyzed[column].any())})


async def anomaly_detection_node(state: PipelineState) -> dict:
    """Detect unusual spend, duplicate charges and category drift.

    Reads unified rows through supabase-mcp, then applies the existing
    z-score / IQR / rule-based / budget-breach detectors unchanged.
    """
    user_id = state.get("user_id")
    if not user_id:
        return {
            "anomaly_result": {"success": False, "error": "state['user_id'] is required"},
            "anomalies": [],
            "anomaly_flags": [],
        }

    limit = state.get("analysis_limit", 1000)
    tools = await get_pipeline_tools()
    result = await _call(tools, "list_transactions", user_id=user_id, limit=limit)
    rows = _ok_records(_as_records(result))

    if not rows:
        error = next((r["error"] for r in result if "error" in r), None)
        if error:
            return {
                "anomaly_result": {"success": False, "error": error, "anomaly_count": 0},
                "anomalies": [],
                "anomaly_flags": [],
            }
        return {
            "anomaly_result": {
                "success": True,
                "rows_analyzed": 0,
                "rows_skipped": 0,
                "anomaly_count": 0,
                "severity_counts": {},
                "flags": [],
            },
            "anomalies": [],
            "anomaly_flags": [],
        }

    analyzable = [row for row in rows if _is_analyzable(row)]
    rows_skipped = len(rows) - len(analyzable)
    if not analyzable:
        return {
            "anomaly_result": {
                "success": True,
                "rows_analyzed": 0,
                "rows_skipped": rows_skipped,
                "anomaly_count": 0,
                "severity_counts": {},
                "flags": [],
            },
            "anomalies": [],
            "anomaly_flags": [],
        }

    frame = _to_detector_frame(analyzable)
    budget_limits = state.get("budget_limits")
    if not budget_limits:
        budget_limits = await asyncio.to_thread(load_budget_limits, user_id)

    analyzed = await asyncio.to_thread(
        detect_all_anomalies, frame, budget_limits=budget_limits or None
    )
    flagged = analyzed[analyzed["Is_Anomaly"].astype(bool)]
    anomalies = _to_anomaly_records(flagged)
    severity_counts = (
        flagged["Severity"].value_counts().to_dict() if not flagged.empty else {}
    )
    flags = _fired_signals(analyzed)

    return {
        "anomaly_flags": flags,
        "anomalies": anomalies,
        "anomaly_result": {
            "success": True,
            "rows_analyzed": int(len(analyzed)),
            "rows_skipped": rows_skipped,
            "anomaly_count": int(len(anomalies)),
            "severity_counts": {str(k): int(v) for k, v in severity_counts.items()},
            "flags": flags,
        },
    }
