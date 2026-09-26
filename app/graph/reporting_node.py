# ==========================================================
# Reporting node (Step 4 stub — real body lands in Step 5)
# ==========================================================
# Exists so the conditional edge has a real target and the routing is proven
# before reporting-mcp is built. Step 5 replaces the body with a
# reporting-mcp call (PDF generation + Gmail/Calendar dispatch) and keeps the
# same state contract: read anomaly_result / anomalies, write report.

from app.graph.state import PipelineState


async def reporting_node(state: PipelineState) -> dict:
    """Placeholder reporting stage: records what it received, generates nothing."""
    anomalies = state.get("anomalies") or []
    anomaly_result = state.get("anomaly_result") or {}
    return {
        "report": {
            "status": "stub",
            "generated": False,
            "reason": "reporting-mcp is not built yet (Step 5)",
            "anomaly_count": anomaly_result.get("anomaly_count", len(anomalies)),
            "flags": state.get("anomaly_flags") or [],
        }
    }
