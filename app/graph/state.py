"""Shared state schema for the CFO pipeline graph.

Every node reads context keys (user_id, trigger, source) and writes only its
own stage output, so the graph stays deterministic and easy to reason about.
The anomaly node populates ``anomalies`` / ``anomaly_flags`` / ``anomaly_result``;
the reporting node populates ``report``.

The supervisor (Step 6) writes ``route`` / ``route_error`` and dispatches into a
subgraph, so ``route`` is the only field that decides which stages run.

``force_report`` is a caller intent, not a routing decision: a scheduled run that
flagged nothing stays quiet, while a run somebody explicitly asked for always
reaches the reporting node.
"""

from typing import TypedDict


class PipelineState(TypedDict, total=False):
    # --- context --------------------------------------------------------- #
    user_id: int
    trigger: str  # "new_data" | "scheduled" | "chat"
    source: str | None  # data source driving this run (e.g. "stripe")
    analysis_limit: int  # rows pulled from unified_transactions for analysis
    budget_limits: dict | None  # optional per-category limits; else from settings
    report_email: str | None  # report recipient override; else from settings
    meeting: dict | None  # optional {attendees, start_time, end_time} dispatch
    question: str | None  # chat trigger: the user's natural-language question
    report_months: int  # how many months back the report reaches; else from settings
    start_date: str | None  # resolved window start, ISO; set by the supervisor
    end_date: str | None  # resolved window end, ISO; set by the supervisor
    force_report: bool  # report even with nothing flagged; set by manual runs

    # --- supervisor ------------------------------------------------------ #
    route: str | None  # "pipeline" | "analyst" | None when unroutable
    route_error: str | None

    # --- stage outputs --------------------------------------------------- #
    anomalies: list[dict]
    anomaly_flags: list[str]
    anomaly_result: dict | None
    report: dict | None
    analyst: dict | None