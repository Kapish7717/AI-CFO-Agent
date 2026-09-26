"""Tests for the anomaly LangGraph node and the conditional edge (Step 4).

Offline: supabase-mcp is faked at the tool layer, so the reshape into the
detector column contract, the detector call, the state contract and the
routing decision are all exercised without touching Supabase.
"""

import json

import pandas as pd
import pytest

from app.graph import anomaly_node as node
from app.graph import pipeline


class _FakeTool:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return self.result


def _envelope(payload):
    """The shape langchain-mcp-adapters really returns."""
    return [{"type": "text", "text": json.dumps(payload), "id": "lc_1"}]


def _rows(n=40, **overrides):
    """Rows with one obvious outlier so the detectors have something to find."""
    out = []
    for i in range(n):
        row = {
            "external_id": f"ch_{i:03d}",
            "amount": 100.0,
            "transaction_date": f"2026-01-{i % 28 + 1:02d}T10:00:00",
            "transaction_type": "expense",
            "counterparty": f"vendor_{i % 5}",
            "category": "Software",
            "source": "stripe",
        }
        row.update(overrides)
        out.append(row)
    return out


def _patch(monkeypatch, rows=None, error=None):
    payload = {"error": error} if error else rows
    tool = _FakeTool("list_transactions", _envelope(payload))
    monkeypatch.setattr(node, "get_pipeline_tools", lambda: _async_value([tool]))
    monkeypatch.setattr(node, "load_budget_limits", lambda user_id: {})
    return tool


async def _async_value(value):
    return value


def test_to_detector_frame_maps_columns_and_types():
    frame = node._to_detector_frame(
        [{"external_id": "ch_1", "amount": "50.5", "transaction_date": "2026-01-05T00:00:00",
          "transaction_type": "expense", "counterparty": "Acme", "category": "Software"}]
    )

    assert frame.loc[0, "Amount"] == 50.5
    assert frame.loc[0, "Type"] == "Expense"
    assert frame.loc[0, "Entity"] == "Acme"
    assert frame.loc[0, "ExternalID"] == "ch_1"


def test_entity_falls_back_to_external_id():
    """A constant fallback would collapse unrelated rows into duplicates."""
    assert node._entity({"external_id": "ch_9", "counterparty": None}) == "ch_9"
    assert node._entity({"external_id": "ch_9", "description": "rent"}) == "rent"
    assert node._entity({}) == "unknown"


@pytest.mark.anyio
async def test_node_flags_outlier(monkeypatch):
    rows = _rows(40)
    rows[7]["amount"] = 99_000.0
    _patch(monkeypatch, rows=rows)

    out = await node.anomaly_detection_node({"user_id": 7})

    assert out["anomaly_result"]["success"] is True
    assert out["anomaly_result"]["rows_analyzed"] == 40
    assert out["anomaly_result"]["anomaly_count"] >= 1
    assert out["anomaly_flags"], "expected at least one fired signal"
    flagged_ids = {a["external_id"] for a in out["anomalies"]}
    assert "ch_007" in flagged_ids
    outlier = next(a for a in out["anomalies"] if a["external_id"] == "ch_007")
    assert outlier["severity"] in {"Medium", "High", "Critical"}
    assert outlier["signals"]


@pytest.mark.anyio
async def test_node_returns_no_flags_when_clean(monkeypatch):
    _patch(monkeypatch, rows=_rows(30))

    out = await node.anomaly_detection_node({"user_id": 7})

    assert out["anomaly_result"]["success"] is True
    assert out["anomaly_result"]["anomaly_count"] == 0
    assert out["anomalies"] == []
    assert out["anomaly_flags"] == []


@pytest.mark.anyio
async def test_node_surfaces_read_error(monkeypatch):
    _patch(monkeypatch, error="No module named 'psycopg2'")

    out = await node.anomaly_detection_node({"user_id": 7})

    assert out["anomaly_result"]["success"] is False
    assert "psycopg2" in out["anomaly_result"]["error"]
    assert out["anomaly_flags"] == []


@pytest.mark.anyio
async def test_node_handles_no_rows(monkeypatch):
    _patch(monkeypatch, rows=[])

    out = await node.anomaly_detection_node({"user_id": 7})

    assert out["anomaly_result"]["success"] is True
    assert out["anomaly_result"]["rows_analyzed"] == 0
    assert out["anomaly_flags"] == []


@pytest.mark.anyio
async def test_node_requires_user_id(monkeypatch):
    out = await node.anomaly_detection_node({})

    assert out["anomaly_result"]["success"] is False
    assert "user_id" in out["anomaly_result"]["error"]


def test_route_after_anomaly():
    assert pipeline.route_after_anomaly(
        {"anomaly_result": {"success": True, "anomaly_count": 3}}
    ) == "reporting"
    assert pipeline.route_after_anomaly(
        {"anomaly_result": {"success": True, "anomaly_count": 0}}
    ) == "end"
    assert pipeline.route_after_anomaly({"anomaly_result": {"success": False}}) == "end"
    assert pipeline.route_after_anomaly({}) == "end"


@pytest.mark.anyio
async def test_graph_routes_to_reporting_when_flagged(monkeypatch):
    """Full graph with stubbed stages: anomalies present -> reporting -> END."""
    async def stub_ingest(state):
        return {"source": "stripe", "sync_result": {"success": True, "record_count": 1}}

    async def stub_anomaly(state):
        return {
            "anomaly_flags": ["zscore"],
            "anomalies": [{"external_id": "ch_1", "severity": "High"}],
            "anomaly_result": {"success": True, "anomaly_count": 1, "rows_analyzed": 10},
        }

    monkeypatch.setattr(pipeline, "stripe_ingestion_node", stub_ingest)
    monkeypatch.setattr(pipeline, "anomaly_detection_node", stub_anomaly)

    graph = pipeline.build_graph()
    result = await graph.ainvoke({"user_id": 1, "trigger": "new_data"})

    assert result["anomaly_result"]["anomaly_count"] == 1
    assert result["report"]["generated"] is False
    assert result["report"]["anomaly_count"] == 1


@pytest.mark.anyio
async def test_graph_skips_reporting_when_clean(monkeypatch):
    async def stub_ingest(state):
        return {"source": "stripe", "sync_result": {"success": True, "record_count": 1}}

    async def stub_anomaly(state):
        return {
            "anomaly_flags": [],
            "anomalies": [],
            "anomaly_result": {"success": True, "anomaly_count": 0, "rows_analyzed": 10},
        }

    monkeypatch.setattr(pipeline, "stripe_ingestion_node", stub_ingest)
    monkeypatch.setattr(pipeline, "anomaly_detection_node", stub_anomaly)

    graph = pipeline.build_graph()
    result = await graph.ainvoke({"user_id": 1, "trigger": "new_data"})

    assert "report" not in result or result["report"] is None


def test_detector_frame_is_not_empty_for_anomalous_input():
    """Guard the reshape: detectors need numeric Amount and a Date column."""
    frame = node._to_detector_frame(_rows(5))

    assert isinstance(frame, pd.DataFrame)
    assert set(["Amount", "Date", "Entity", "Type", "Category"]) <= set(frame.columns)
    assert pd.api.types.is_numeric_dtype(frame["Amount"])


def test_is_analyzable_rejects_junk_rows():
    """0-amount / epoch-date leftovers must not reach the detectors."""
    assert node._is_analyzable({"amount": 12.5, "transaction_date": "2026-01-05T00:00:00"})
    assert not node._is_analyzable({"amount": 0, "transaction_date": "2026-01-05T00:00:00"})
    assert not node._is_analyzable({"amount": 0.0, "transaction_date": "1970-01-01T00:00:00"})
    assert not node._is_analyzable({"amount": None, "transaction_date": "2026-01-05T00:00:00"})
    assert not node._is_analyzable({"amount": 10, "transaction_date": None})
    assert not node._is_analyzable({"amount": 10, "transaction_date": "not-a-date"})


@pytest.mark.anyio
async def test_node_skips_junk_rows_and_reports_count(monkeypatch):
    """Junk rows are excluded from analysis but counted, never silently dropped."""
    rows = _rows(20)
    for i in range(5):
        rows.append(
            {"external_id": f"lc_{i}", "amount": 0.0, "transaction_date": "1970-01-01T00:00:00",
             "transaction_type": "expense", "counterparty": None, "category": "expense"}
        )
    rows.append(
        {"external_id": "lc_nodate", "amount": 42.0, "transaction_date": None,
         "transaction_type": "expense", "counterparty": None, "category": "expense"}
    )
    _patch(monkeypatch, rows=rows)

    out = await node.anomaly_detection_node({"user_id": 7})

    assert out["anomaly_result"]["success"] is True
    assert out["anomaly_result"]["rows_analyzed"] == 20
    assert out["anomaly_result"]["rows_skipped"] == 6
    assert not any(str(a["external_id"]).startswith("lc_") for a in out["anomalies"])


@pytest.mark.anyio
async def test_node_handles_all_rows_junk(monkeypatch):
    _patch(
        monkeypatch,
        rows=[
            {"external_id": "lc_1", "amount": 0.0, "transaction_date": "1970-01-01T00:00:00",
             "transaction_type": "expense", "counterparty": None, "category": "expense"}
        ],
    )

    out = await node.anomaly_detection_node({"user_id": 7})

    assert out["anomaly_result"]["success"] is True
    assert out["anomaly_result"]["rows_analyzed"] == 0
    assert out["anomaly_result"]["rows_skipped"] == 1
    assert out["anomaly_flags"] == []
