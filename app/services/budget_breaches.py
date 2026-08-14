"""Budget breach JSON generation.

Whenever the user saves their department budgets, this module recomputes the
budget breaches from the stored transactions and pushes the summary to Supabase
Storage as ``breaches/budget_breaches_{user_id}.json``. Downstream consumers
(agents, dashboard, email reports) read that JSON, so it must always be fresh.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import pandas as pd

# Settings field -> category name used in transaction data.
CATEGORY_MAP: dict[str, str] = {
    "budget_marketing": "Marketing",
    "budget_operations": "Operations",
    "budget_travel": "Travel",
}


def refresh_budget_breaches(user_id: int) -> list[dict[str, Any]]:
    """Recompute budget breaches for a user and upload the summary to storage.

    Returns the list of breach records that was written (may be empty when the
    user has no data or nothing exceeds their budgets).
    """
    from app.db.database import get_user_settings, get_user_transactions
    from app.db.storage import upload_to_storage

    summary: list[dict[str, Any]] = []

    try:
        settings = get_user_settings(user_id)

        budget_limits: dict[str, float] = {}
        for field, category in CATEGORY_MAP.items():
            raw = settings.get(field)
            try:
                limit = float(raw) if raw else 0.0
            except (TypeError, ValueError):
                limit = 0.0
            if limit > 0:
                budget_limits[category] = limit

        rows = get_user_transactions(user_id)

        breaches_file = f"uploads/budget_breaches_{user_id}.json"

        if rows and budget_limits:
            df = pd.DataFrame(rows)
            if "Type" in df.columns and "Date" in df.columns and not df.empty:
                df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                from app.tools.anomaly_detection import detect_budget_breaches

                df = detect_budget_breaches(df, budget_limits=budget_limits)
                breaches = df[df["Is_Budget_Breach"] == True].copy()  # noqa: E712
                if not breaches.empty:
                    breaches["MonthYear"] = breaches["Date"].dt.strftime("%b %Y")
                    breaches = breaches.drop_duplicates(subset=["Category", "MonthYear"])
                    summary = json.loads(breaches.to_json(orient="records", date_format="iso"))
        else:
            # No transactions or no budgets configured: nothing to report.
            summary = []

        os.makedirs("uploads", exist_ok=True)
        with open(breaches_file, "w") as f:
            json.dump(summary, f, indent=2, default=str)

        upload_to_storage(breaches_file, f"breaches/budget_breaches_{user_id}.json")
        sys.stderr.write(f"[BUDGET BREACHES] Refreshed {len(summary)} breaches for user {user_id}.\n")
    except Exception as e:
        sys.stderr.write(f"[BUDGET BREACHES ERROR] Failed to refresh breaches: {e}\n")

    return summary
