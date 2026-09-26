"""Shared state schema for the CFO pipeline graph.

Every node reads context keys (user_id, trigger, source) and writes only its
own stage output, so the graph stays deterministic and easy to reason about.
The anomaly node populates ``anomalies`` / ``anomaly_flags`` / ``anomaly_result``;
the reporting node populates ``report`` (still a stub until Step 5).
"""

from typing import TypedDict


class PipelineState(TypedDict, total=False):
    # --- context --------------------------------------------------------- #
    user_id: int
    trigger: str  # "new_data" | "scheduled" | "chat"
    source: str | None  # data source driving this run (e.g. "stripe")
    fetch_limit: int  # per-fetch page size for the stripe-mcp tools
    analysis_limit: int  # rows pulled from unified_transactions for analysis
    budget_limits: dict | None  # optional per-category limits; else from settings

    # --- stage outputs --------------------------------------------------- #
    sync_result: dict | None
    anomalies: list[dict]
    anomaly_flags: list[str]
    anomaly_result: dict | None
    report: dict | None