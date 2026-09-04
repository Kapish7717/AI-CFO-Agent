"""Deterministic report-content evaluation harness.

This module scores the *output* of the CFO PDF report — the numbers and facts
that actually end up in the document — against golden expectations recorded in
``tests/eval_sets/report_content.json``.

It complements ``agent_trajectory.py``: trajectory evaluation grades *behaviour*
(which tools the agent called and with what args), while this grades *content*
(whether the report's KPIs, anomaly rows, and monthly figures are correct).

Two pieces:

1. ``extract_report_content`` — reads a generated PDF with pdfplumber and pulls
   out the deterministic values: KPI cards (gross revenue, total expenses, net
   profit, avg burn rate), the anomaly table rows, the monthly revenue table,
   and the narrative text.

2. ``score_report_content`` — compares that extraction against golden
   expectations and produces metrics:

   - ``kpi_accuracy`` — do the KPI card values match the expected numbers?
   - ``anomaly_recall`` / ``anomaly_precision`` — are the expected anomaly rows
     present, with no extras?
   - ``monthly_accuracy`` — does the monthly revenue breakdown match?
   - ``count_ok`` — does the "N total anomalies" banner match?
   - ``narrative_facts_ok`` — do dollar figures mentioned in the LLM narrative
     contradict the known totals (hallucination check)?

   ``score`` is a weighted 0..1 combination; ``passed`` is True when the golden
   threshold is met.

The golden test drives the real ``ReportGenerator`` on a hand-verified fixture
dataset (with ``GROQ_API_KEY`` blanked so the LLM narrative is deterministic and
offline), proving the whole report pipeline produces correct content. A
corrupted extraction is also scored to prove the gate detects wrong numbers.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import pdfplumber

EVAL_SETS_DIR = os.path.join(os.path.dirname(__file__), "..", "eval_sets")

KPI_LABELS = ("Gross Revenue", "Total Expenses", "Net Profit", "Avg Burn Rate")
ANOMALY_BANNER_RE = re.compile(r"(\d+)\s+total anomalies flagged for review")

# Weighted combination, must sum to 1.0.
WEIGHTS = {"kpi": 0.40, "anomaly": 0.30, "monthly": 0.20, "count": 0.05, "facts": 0.05}


# --------------------------------------------------------------------------- #
# Extraction model
# --------------------------------------------------------------------------- #
@dataclass
class ReportContent:
    kpis: dict[str, float] = field(default_factory=dict)
    anomaly_rows: list[dict[str, Any]] = field(default_factory=list)
    monthly_revenue: list[dict[str, Any]] = field(default_factory=list)
    total_anomalies: int = 0
    narrative: str = ""


def _to_float(value: Any) -> float | None:
    """Parse a currency string like '$8,316.67' or '8,316.67/mo' to a float."""
    m = re.search(r"\$?\s?([\d,]+\.\d{2})", str(value))
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _header_of(table: list[list]) -> list[str]:
    if not table or not table[0]:
        return []
    return [str(c).strip() if c else "" for c in table[0]]


def _rows_after(table: list[list]) -> list[list]:
    return [r for r in table[1:] if r and any(r)]


def _extract_narrative_text(pdf) -> str:
    """Reconstruct the report's prose (paragraphs), excluding table regions.

    Tables contain the deterministic figures (KPIs, anomaly rows, monthly
    revenue) — those must not leak into the narrative fact-check, which exists
    only to catch hallucinated numbers in the LLM-written sections.
    """
    parts: list[str] = []
    for page in pdf.pages:
        bboxes = [t.bbox for t in page.find_tables()]

        def in_table(word, table_bboxes) -> bool:
            cx = (word["x0"] + word["x1"]) / 2
            cy = (word["top"] + word["bottom"]) / 2
            return any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in table_bboxes)

        words = [w for w in page.extract_words() if not in_table(w, bboxes)]
        words.sort(key=lambda w: (round(w["top"], 1), w["x0"]))
        parts.append(" ".join(w["text"] for w in words))
    return "\n".join(parts)


def extract_report_content(pdf_path: str) -> ReportContent:
    """Parse a generated CFO PDF into its deterministic report content."""
    content = ReportContent()
    tables: list[list[list]] = []
    text_pages: list[str] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text_pages.append(page.extract_text() or "")
            tables.extend(page.extract_tables() or [])
        content.narrative = _extract_narrative_text(pdf)

    # KPI cards ------------------------------------------------------------ #
    for table in tables:
        for row in table:
            for cell in row:
                if not cell:
                    continue
                cell_text = str(cell)
                for label in KPI_LABELS:
                    if label in cell_text:
                        value = _to_float(cell_text.split("\n")[-1])
                        if value is not None:
                            content.kpis[label] = value

    # Anomaly table -------------------------------------------------------- #
    for table in tables:
        header = _header_of(table)
        if "Entity" in header and "Severity" in header:
            idx = {h: i for i, h in enumerate(header)}
            for row in _rows_after(table):
                content.anomaly_rows.append({
                    "date": str(row[idx.get("Date", 0)] or "").strip(),
                    "type": str(row[idx.get("Type", 1)] or "").strip(),
                    "entity": str(row[idx.get("Entity", 2)] or "").strip(),
                    "amount": _to_float(row[idx.get("Amount", 3)]),
                    "severity": str(row[idx.get("Severity", 4)] or "").strip(),
                    "reason": str(row[idx.get("Reason", 5)] or "").strip(),
                })
            break

    # Monthly revenue table ------------------------------------------------ #
    for table in tables:
        header = _header_of(table)
        if "Month" in header and "Total Revenue" in header:
            idx = {h: i for i, h in enumerate(header)}
            for row in _rows_after(table):
                content.monthly_revenue.append({
                    "month": str(row[idx.get("Month", 0)] or "").strip(),
                    "total": _to_float(row[idx.get("Total Revenue", 1)]),
                })
            break

    # Anomaly count banner -------------------------------------------------- #
    m = ANOMALY_BANNER_RE.search(content.narrative)
    if m:
        content.total_anomalies = int(m.group(1))

    return content


# --------------------------------------------------------------------------- #
# Narrative fact-checking
# --------------------------------------------------------------------------- #
def check_narrative_facts(text: str, ground_truth: dict[str, float]) -> list[str]:
    """Flag dollar amounts in the narrative that match no known total.

    The LLM narrative is non-deterministic, so we can't assert its exact text —
    but we *can* catch hallucinations: if it cites a figure that contradicts
    every real total (revenue, expenses, profit), the report is wrong.
    """
    amounts = [float(m.replace(",", "")) for m in re.findall(r"\$([\d,]+(?:\.\d+)?)", text)]
    truths = [v for v in ground_truth.values() if isinstance(v, (int, float))]
    violations = []
    for a in amounts:
        if not any(abs(a - t) <= max(1.0, 0.01 * abs(t)) for t in truths):
            violations.append(f"narrative cites ${a:,.2f} which matches no known total")
    return violations


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def score_report_content(
    expected: dict[str, Any],
    actual: ReportContent,
    threshold: float = 1.0,
) -> dict[str, Any]:
    """Score extracted report content against golden expectations."""
    # KPI accuracy --------------------------------------------------------- #
    kpi_checks = list(expected.get("expected_kpis", {}).items())
    kpi_passed = 0
    kpi_violations: list[str] = []
    for label, exp_value in kpi_checks:
        got = actual.kpis.get(label)
        if got is not None and abs(got - exp_value) <= 0.01:
            kpi_passed += 1
        else:
            kpi_violations.append(f"{label}: expected {exp_value}, got {got}")
    kpi_accuracy = kpi_passed / len(kpi_checks) if kpi_checks else 1.0

    # Anomaly match (by entity + amount, plus severity) -------------------- #
    exp_anoms = expected.get("expected_anomalies", [])
    found = []
    for ea in exp_anoms:
        matched = any(
            a["entity"] == ea.get("entity")
            and a["amount"] is not None
            and abs(a["amount"] - ea.get("amount", 0)) <= 0.01
            and (not ea.get("severity") or a["severity"] == ea.get("severity"))
            for a in actual.anomaly_rows
        )
        found.append(matched)
    anomaly_recall = sum(found) / len(exp_anoms) if exp_anoms else 1.0
    extra_anomalies = [
        a for a in actual.anomaly_rows
        if not any(
            a["entity"] == ea.get("entity")
            and abs((a["amount"] or 0) - ea.get("amount", 0)) <= 0.01
            for ea in exp_anoms
        )
    ]
    anomaly_precision = (
        (len(exp_anoms) - len(extra_anomalies)) / len(actual.anomaly_rows)
        if actual.anomaly_rows
        else (1.0 if not exp_anoms else 0.0)
    )
    anomaly_violations = [
        f"anomaly {ea.get('entity')} ({ea.get('amount')}) missing" for ea, f in zip(exp_anoms, found, strict=False) if not f
    ]
    anomaly_violations += [f"unexpected anomaly {a['entity']} ({a['amount']})" for a in extra_anomalies]

    # Monthly revenue ------------------------------------------------------ #
    exp_monthly = expected.get("expected_monthly_revenue", [])
    monthly_passed = 0
    monthly_violations: list[str] = []
    for m in exp_monthly:
        matched = any(
            am["total"] is not None
            and am["month"] == m.get("month")
            and abs(am["total"] - m.get("total", 0)) <= 0.01
            for am in actual.monthly_revenue
        )
        monthly_passed += 1 if matched else 0
        if not matched:
            monthly_violations.append(f"month {m.get('month')}: expected {m.get('total')} not found")
    monthly_accuracy = monthly_passed / len(exp_monthly) if exp_monthly else 1.0

    # Anomaly count banner -------------------------------------------------- #
    exp_count = expected.get("expected_total_anomalies")
    count_ok = exp_count is None or actual.total_anomalies == exp_count

    # Narrative fact consistency ------------------------------------------- #
    facts = check_narrative_facts(actual.narrative, expected.get("narrative_ground_truth", {}))
    facts_ok = len(facts) == 0

    # Weighted combination --------------------------------------------------- #
    anomaly = (anomaly_recall + anomaly_precision) / 2
    score = (
        WEIGHTS["kpi"] * kpi_accuracy
        + WEIGHTS["anomaly"] * anomaly
        + WEIGHTS["monthly"] * monthly_accuracy
        + WEIGHTS["count"] * (1.0 if count_ok else 0.0)
        + WEIGHTS["facts"] * (1.0 if facts_ok else 0.0)
    )
    rounded_score = round(score, 4)

    return {
        "kpi_accuracy": round(kpi_accuracy, 4),
        "anomaly_recall": round(anomaly_recall, 4),
        "anomaly_precision": round(anomaly_precision, 4),
        "monthly_accuracy": round(monthly_accuracy, 4),
        "count_ok": count_ok,
        "narrative_facts_ok": facts_ok,
        "kpi_violations": kpi_violations,
        "anomaly_violations": anomaly_violations,
        "monthly_violations": monthly_violations,
        "narrative_violations": facts,
        "score": rounded_score,
        "passed": rounded_score >= threshold,
    }


# --------------------------------------------------------------------------- #
# Golden set loading and report generation
# --------------------------------------------------------------------------- #
def load_eval_set(name: str = "report_content.json") -> dict:
    path = os.path.abspath(os.path.join(EVAL_SETS_DIR, name))
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def generate_golden_report(case: dict[str, Any], output_path: str) -> str:
    """Generate a real CFO PDF from a golden dataset and return its path.

    Mirrors the agent pipeline: ingest raw rows -> run anomaly detection ->
    generate the report. Requires ``GROQ_API_KEY`` to be unset so the LLM
    narrative falls back to the deterministic offline stub.
    """
    import pandas as pd

    from app.tools.anomaly_detection import detect_all_anomalies
    from app.tools.report_generator import ReportGenerator

    dataset = case["dataset"] if "dataset" in case else _dataset_for_case(case)
    df = pd.DataFrame(dataset["rows"], columns=dataset["columns"])
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

    analyzed = detect_all_anomalies(df, budget_limits={})

    generator = ReportGenerator(
        analyzed,
        output_path=output_path,
        budget_breaches=[],
        breaches_file="nonexistent_budget_breaches.json",
    )
    generator.generate_pdf()
    return output_path


def _dataset_for_case(case: dict[str, Any]) -> dict:
    data = load_eval_set()
    return data["dataset"]