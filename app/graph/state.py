"""Shared state schema for the CFO pipeline graph.

Every node reads context keys (user_id, trigger, source) and writes only its
own stage output, so the graph stays deterministic and easy to reason about.
Later steps populate ``anomalies`` / ``anomaly_flags`` (anomaly node) and
``report`` (reporting node).
"""

from typing import TypedDict


class PipelineState(TypedDict, total=False):
    # --- context --------------------------------------------------------- #
    user_id: int
    trigger: str  # "new_data" | "scheduled" | "chat"
    source: str | None  # data source driving this run (e.g. "stripe")
    fetch_limit: int  # per-fetch page size for the stripe-mcp tools

    # --- stage outputs --------------------------------------------------- #
    sync_result: dict | None
    anomalies: list[dict]
    anomaly_flags: list[str]
    report: dict | None