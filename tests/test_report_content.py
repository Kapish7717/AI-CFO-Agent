"""Tests for the report-content evaluation harness.

Verifies that (a) the real report pipeline produces a PDF whose numbers match
hand-computed ground truth, (b) the scorer genuinely catches wrong content — a
bad KPI, a missing anomaly, or a hallucinated narrative figure — and (c) the
eval-set schema is valid.
"""

import re

import pytest

from tests.evals.report_content import (
    ReportContent,
    check_narrative_facts,
    extract_report_content,
    generate_golden_report,
    load_eval_set,
    score_report_content,
)

GOLDEN_THRESHOLD = 1.0


def _golden_cases():
    return load_eval_set()["cases"]


def _quotable_monthly(case):
    """The monthly totals a narrative may legitimately quote.

    Mirrors what ``score_report_content`` passes to the fact-check, so these tests
    exercise the same allowlist the scorer uses.
    """
    return [
        m["total"]
        for key in ("expected_monthly_revenue", "expected_monthly_expenses")
        for m in case.get(key, [])
    ]


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


class TestNarrativeGroundTruthCoversThePrompt:
    """Every figure the prompt offers must be quotable without tripping the check.

    The narrative is built from a fixed data block, so the model can legitimately
    quote any figure in it. ``check_narrative_facts`` flags any dollar amount that
    matches no known total, which means the allowlist has to stay in step with the
    block: a figure added to the prompt but not to the allowlist turns correct
    output into a "hallucination" failure.

    That gap was live for a while. The golden test blanks ``GROQ_API_KEY`` so the
    narrative falls back to a stub with no figures in it, which is the only reason
    a stale allowlist went unnoticed. These tests exercise the check directly
    instead of relying on the stub.
    """

    @staticmethod
    def _prompt_figures(case):
        """The dollar amounts the real prompt puts in front of the model."""
        import pandas as pd

        from app.tools.anomaly_detection import detect_all_anomalies
        from app.tools.report_generator import ReportGenerator
        from tests.evals.report_content import _dataset_for_case

        dataset = _dataset_for_case(case)
        df = pd.DataFrame(dataset["rows"], columns=dataset["columns"])
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        analyzed = detect_all_anomalies(df, budget_limits={})

        generator = ReportGenerator(
            analyzed, output_path="unused.pdf", llm_config={"api_key": "k"}
        )
        prompts = []

        class Recorder:
            @staticmethod
            def invoke(messages, config=None):
                prompts.append(messages[1]["content"])
                return type("R", (), {"content": "ok"})()

        import app.services.llm_factory as llm_factory

        original = llm_factory.create_llm
        llm_factory.create_llm = lambda **kw: Recorder()
        try:
            generator.generate_llm_narrative()
        finally:
            llm_factory.create_llm = original

        assert prompts, "no prompt was captured"
        return {
            float(m.replace(",", ""))
            for p in prompts
            for m in re.findall(r"\$([\d,]+(?:\.\d+)?)", p)
        }

    def test_no_figure_offered_by_the_prompt_is_flagged(self):
        case = _golden_cases()[0]
        figures = self._prompt_figures(case)
        assert figures, "the prompt offered no dollar figures to check"

        monthly = _quotable_monthly(case)
        violations = check_narrative_facts(
            "Totals: " + ", ".join(f"${v:,.2f}" for v in sorted(figures)),
            case["narrative_ground_truth"],
            extra_truths=monthly,
        )
        assert violations == [], (
            "the narrative prompt quotes figures the fact-check does not allow; "
            f"add them to narrative_ground_truth: {violations}"
        )

    def test_a_genuinely_invented_figure_is_still_caught(self):
        # The counterpart to the test above: widening the allowlist must not blunt
        # the check, or it stops being a hallucination detector.
        case = _golden_cases()[0]
        monthly = _quotable_monthly(case)
        violations = check_narrative_facts(
            "We banked $77,777,777.00 this year.",
            case["narrative_ground_truth"],
            extra_truths=monthly,
        )
        assert violations, "an invented total must still be flagged"

    def test_the_monthly_series_is_quotable(self):
        case = _golden_cases()[0]
        assert check_narrative_facts(
            "January revenue was $8,000.00.", case["narrative_ground_truth"]
        ), "the series alone is not enough; it must be passed as extra_truths"
        assert check_narrative_facts(
            "January revenue was $8,000.00.",
            case["narrative_ground_truth"],
            extra_truths=_quotable_monthly(case),
        ) == []

    def test_monthly_expenses_are_quotable_too(self):
        # The prompt offers month-wise expenses alongside month-wise revenue. Only
        # the revenue series used to be recorded, so a narrative quoting a real
        # expense month was reported as hallucinating one.
        case = _golden_cases()[0]
        assert case["expected_monthly_expenses"], "golden set is missing the expense series"
        assert check_narrative_facts(
            "February expenses were $12,900.00.",
            case["narrative_ground_truth"],
            extra_truths=_quotable_monthly(case),
        ) == []

    def test_average_monthly_spend_is_allowlisted(self):
        # The prompt labels the period burn explicitly and offers average monthly
        # spend beside it, so a narrative may legitimately quote either. The
        # average is the same number as the Avg Burn Rate KPI card.
        case = _golden_cases()[0]
        assert case["narrative_ground_truth"]["avg_monthly_spend"] == pytest.approx(
            case["expected_kpis"]["Avg Burn Rate"]
        )
        assert check_narrative_facts(
            "Average monthly spend was $8,316.67.",
            case["narrative_ground_truth"],
        ) == []


class TestScorerPassesTheAllowlistThrough:
    """The scorer must actually hand the allowlist to the check.

    The tests above call ``check_narrative_facts`` directly, so they pin the
    contract but say nothing about ``score_report_content``. If the scorer stopped
    forwarding the monthly series, every direct test would still pass while real
    reports started failing on legitimate figures. These drive the scorer instead.
    """

    @staticmethod
    def _scored(case, narrative):
        return score_report_content(
            case,
            ReportContent(
                kpis=case["expected_kpis"],
                anomaly_rows=[
                    {"entity": "Big Spike LLC", "amount": 12000.0, "severity": "High"}
                ],
                monthly_revenue=case["expected_monthly_revenue"],
                total_anomalies=1,
                narrative=narrative,
            ),
            threshold=GOLDEN_THRESHOLD,
        )

    def test_a_narrative_quoting_both_monthly_series_passes(self):
        case = _golden_cases()[0]
        result = self._scored(
            case,
            "Revenue was $25,500.00 with average monthly spend of $8,316.67. "
            "January revenue was $8,000.00 and February expenses were $12,900.00.",
        )
        assert result["narrative_facts_ok"] is True, result["narrative_violations"]
        assert result["narrative_violations"] == []

    def test_an_invented_figure_still_fails_the_scorer(self):
        case = _golden_cases()[0]
        result = self._scored(
            case,
            "Revenue was $25,500.00 and expenses were $24,950.00, "
            "but payroll alone ran to $19,000,000.00.",
        )
        assert result["narrative_facts_ok"] is False
        assert result["passed"] is False
        assert result["narrative_violations"]
