"""Tests for the report-content evaluation harness.

Verifies that (a) the real report pipeline produces a PDF whose numbers match
hand-computed ground truth, (b) the scorer genuinely catches wrong content — a
bad KPI, a missing anomaly, or a hallucinated narrative figure — and (c) the
eval-set schema is valid.
"""

from tests.evals.report_content import (
    ReportContent,
    extract_report_content,
    generate_golden_report,
    load_eval_set,
    score_report_content,
)

GOLDEN_THRESHOLD = 1.0


def _golden_cases():
    return load_eval_set()["cases"]


def test_eval_set_schema_is_valid():
    data = load_eval_set()
    assert data["version"] == 1
    assert data["dataset"]["columns"] and data["dataset"]["rows"]
    assert len(data["cases"]) >= 1
    for case in data["cases"]:
        assert case["id"]
        assert case["expected_kpis"]
        assert case["expected_monthly_revenue"]
        assert isinstance(case.get("expected_anomalies"), list)
        assert "narrative_ground_truth" in case


def test_golden_report_scores_perfect(tmp_path, monkeypatch):
    """The real report pipeline must render every golden value correctly."""
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.chdir(tmp_path)

    case = _golden_cases()[0]
    pdf = generate_golden_report(case, str(tmp_path / "report.pdf"))

    actual = extract_report_content(pdf)
    result = score_report_content(case, actual, threshold=GOLDEN_THRESHOLD)

    assert result["score"] == 1.0, result
    assert result["passed"], result
    assert result["kpi_violations"] == []
    assert result["anomaly_violations"] == []
    assert result["monthly_violations"] == []
    assert result["narrative_violations"] == []


def test_wrong_kpi_value_is_caught():
    """A report with a wrong number in a KPI card must fail the gate."""
    case = _golden_cases()[0]
    actual = ReportContent(
        kpis={
            "Gross Revenue": 99999.0,  # wrong
            "Total Expenses": 24950.0,
            "Net Profit": 550.0,
            "Avg Burn Rate": 8316.67,
        },
        anomaly_rows=[
            {"entity": "Big Spike LLC", "amount": 12000.0, "severity": "High"}
        ],
        monthly_revenue=[
            {"month": "Jan 2026", "total": 8000.0},
            {"month": "Feb 2026", "total": 8500.0},
            {"month": "Mar 2026", "total": 9000.0},
        ],
        total_anomalies=1,
        narrative="",
    )
    result = score_report_content(case, actual, threshold=GOLDEN_THRESHOLD)
    assert result["passed"] is False
    assert any("Gross Revenue" in v for v in result["kpi_violations"])
    assert result["kpi_accuracy"] < 1.0


def test_missing_anomaly_is_caught():
    """A report that fails to surface a flagged anomaly must fail the gate."""
    case = _golden_cases()[0]
    actual = ReportContent(
        kpis=case["expected_kpis"],
        anomaly_rows=[],  # Big Spike LLC missing
        monthly_revenue=case["expected_monthly_revenue"],
        total_anomalies=0,
        narrative="",
    )
    result = score_report_content(case, actual, threshold=GOLDEN_THRESHOLD)
    assert result["passed"] is False
    assert any("Big Spike LLC" in v for v in result["anomaly_violations"])
    assert result["anomaly_recall"] < 1.0


def test_wrong_monthly_revenue_is_caught():
    """A report with a wrong monthly revenue figure must fail the gate."""
    case = _golden_cases()[0]
    actual = ReportContent(
        kpis=case["expected_kpis"],
        anomaly_rows=[
            {"entity": "Big Spike LLC", "amount": 12000.0, "severity": "High"}
        ],
        monthly_revenue=[
            {"month": "Jan 2026", "total": 8000.0},
            {"month": "Feb 2026", "total": 99999.0},  # wrong
            {"month": "Mar 2026", "total": 9000.0},
        ],
        total_anomalies=1,
        narrative="",
    )
    result = score_report_content(case, actual, threshold=GOLDEN_THRESHOLD)
    assert result["passed"] is False
    assert result["monthly_accuracy"] < 1.0
    assert any("Feb 2026" in v for v in result["monthly_violations"])


def test_narrative_hallucination_is_caught():
    """A narrative that cites a figure contradicting the real totals must fail."""
    case = _golden_cases()[0]
    actual = ReportContent(
        kpis=case["expected_kpis"],
        anomaly_rows=[
            {"entity": "Big Spike LLC", "amount": 12000.0, "severity": "High"}
        ],
        monthly_revenue=case["expected_monthly_revenue"],
        total_anomalies=1,
        narrative="Revenue was a record $99,999,999.00 this quarter.",
    )
    result = score_report_content(case, actual, threshold=GOLDEN_THRESHOLD)
    assert result["passed"] is False
    assert result["narrative_facts_ok"] is False
    assert result["narrative_violations"] != []