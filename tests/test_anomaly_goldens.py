"""Golden/fixture regression tests for anomaly detection.

Loads a frozen dataset from ``tests/fixtures/anomaly_dataset.csv`` and asserts that
``detect_all_anomalies`` produces the exact anomaly flags, severities and budget
breach numbers recorded in ``expected_anomalies.json``.

These assertions act as a regression lock: any refactor that silently changes how
anomalies are flagged or scored will fail here. Update the golden files ONLY when
a change in detection behaviour is intentional and reviewed.
"""

import json
import os
from collections import defaultdict

import pandas as pd
import pytest

from app.tools.anomaly_detection import detect_all_anomalies

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _identity_groups(expected: dict) -> dict:
    """Group expected rows by (date, entity, amount).

    Duplicate transactions share an identity, so a single group may describe
    multiple identical rows (e.g. the Google Ads pair).
    """
    groups = defaultdict(list)
    for exp in expected["rows"]:
        groups[(exp["date"], exp["entity"], exp["amount"])].append(exp)
    return groups


def _select_rows(analyzed: pd.DataFrame, identity: tuple) -> pd.DataFrame:
    date, entity, amount = identity
    mask = (
        (analyzed["Date"] == pd.Timestamp(date))
        & (analyzed["Entity"] == entity)
        & (analyzed["Amount"] == amount)
    )
    return analyzed[mask]


@pytest.fixture(scope="module")
def expected() -> dict:
    with open(os.path.join(FIXTURES, "expected_anomalies.json")) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def analyzed() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(FIXTURES, "anomaly_dataset.csv"))
    df["Date"] = pd.to_datetime(df["Date"])
    with open(os.path.join(FIXTURES, "budget_limits.json")) as f:
        budget_limits = json.load(f)
    return detect_all_anomalies(df, budget_limits=budget_limits)


def test_anomaly_signals_match_golden(analyzed: pd.DataFrame, expected: dict):
    """Every data-level signal column must match the frozen expectations."""
    for identity, exps in _identity_groups(expected).items():
        matching = _select_rows(analyzed, identity)
        assert len(matching) == len(exps), identity
        ref = exps[0]
        for _, row in matching.iterrows():
            assert bool(row["Is_Anomaly"]) is ref["is_anomaly"], identity
            assert bool(row["Is_Budget_Breach"]) is ref["is_budget_breach"], identity
            assert bool(row["is_duplicate"]) is ref["is_duplicate"], identity
            assert bool(row["is_large_amount"]) is ref["is_large_amount"], identity
            assert bool(row["is_mom_anomaly"]) is ref["is_mom_anomaly"], identity
            assert bool(row["Anomaly_IQR"]) is ref["is_outlier"], identity


def test_severity_levels_match_golden(analyzed: pd.DataFrame, expected: dict):
    for identity, exps in _identity_groups(expected).items():
        matching = _select_rows(analyzed, identity)
        assert len(matching) == len(exps), identity
        for _, row in matching.iterrows():
            assert row["Severity"] == exps[0]["severity"], identity


def test_aggregate_metrics_match_golden(analyzed: pd.DataFrame, expected: dict):
    agg = expected["aggregate"]
    assert len(analyzed) == agg["total_rows"]
    assert int(analyzed["Is_Anomaly"].sum()) == agg["anomaly_count"]

    severities = (
        analyzed["Severity"]
        .value_counts()
        .reindex(list(agg["severity_counts"].keys()))
        .fillna(0)
        .astype(int)
        .to_dict()
    )
    assert severities == agg["severity_counts"]


def test_budget_breach_amounts_match_golden(analyzed: pd.DataFrame, expected: dict):
    breached = analyzed[analyzed["Is_Budget_Breach"]].drop_duplicates(subset=["Category"])
    for exp in expected["budget_breaches"]:
        row = breached.loc[breached["Category"] == exp["category"]].iloc[0]
        assert float(row["Limit"]) == exp["limit"]
        assert float(row["Actual"]) == exp["actual"]
        assert float(row["Overspend"]) == exp["overspend"]
        assert row["Percent_Over"] == exp["percent_over"]


def test_row_identity_and_order_preserved(analyzed: pd.DataFrame):
    # The engine must never drop or reorder transactions.
    assert len(analyzed) == 12
    assert list(analyzed["Entity"]) == [
        "GitHub", "GitHub", "GitHub", "GitHub",
        "Google Ads", "Google Ads", "Meta Ads", "Uber",
        "AWS", "Acme Corp", "Acme Corp", "Beta Inc",
    ]
