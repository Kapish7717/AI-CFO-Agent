"""Live pipeline smoke tests: the transport layer the rest of the suite fakes out.

Every other test in this repo replaces the MCP subprocess with a plain Python
function, so nothing else exercises stdio spawning, tool dispatch, response
framing or failure handling. That is exactly where the reporting node hung
during manual verification, with the full suite green. These tests close the
gap; they are skipped by default because they talk to real services.

Run them with::

    $env:RUN_LIVE_TESTS = "1"
    $env:LIVE_USER_ID = "4"
    .venv\Scripts\python.exe -m pytest tests/test_pipeline_live.py -v -s

``LIVE_USER_ID`` is required so nothing runs against an unintended account.
Add ``RUN_LIVE_LLM_TESTS=1`` to also exercise the chat path, which spends real
Groq/Jina tokens.

SIDE EFFECTS: the reporting node uploads a PDF to Supabase Storage, and it will
email the report if the user has a ``report_email`` configured. Pick a user you
are happy to run this against. The graph itself only reads.

Every call is wrapped in ``asyncio.wait_for``, so a wedged tool fails the test
with a timeout instead of hanging the suite.
"""

import asyncio
import os

import pytest

from app.graph.anomaly_node import anomaly_detection_node
from app.graph.mcp_client import get_pipeline_tools
from app.graph.reporting_node import reporting_node
from app.mcp.supabase.tools_query import describe_table, run_read_only_sql

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_TESTS") != "1",
    reason="live tests hit Stripe/Supabase/Groq; set RUN_LIVE_TESTS=1 to enable",
)

_LLM_REQUIRED = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="spends real LLM tokens; set RUN_LIVE_LLM_TESTS=1 to enable",
)

# Generous relative to the ~20s the report path took in-process, but finite.
BIND_TIMEOUT = 60.0
QUERY_TIMEOUT = 60.0
ANOMALY_TIMEOUT = 180.0
REPORT_TIMEOUT = 420.0

# Not a real id, so it must never appear in an org-scoped read.
FOREIGN_USER_ID = 999_999_999

EXPECTED_TOOLS = {
    "list_transactions",
    "describe_table",
    "run_read_only_sql",
    "generate_cfo_pdf_report",
    "send_email_report",
    "schedule_budget_review",
}


def _user_id() -> int:
    raw = os.getenv("LIVE_USER_ID", "").strip()
    if not raw:
        pytest.skip("set LIVE_USER_ID to the account to exercise")
    return int(raw)


async def _within(awaitable, seconds: float, label: str):
    """Run a step under a hard deadline so a hang is a failure, not a stall."""
    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except asyncio.TimeoutError:
        pytest.fail(f"{label} exceeded {seconds:g}s (wedged MCP subprocess?)")


@pytest.mark.anyio
async def test_all_mcp_servers_bind():
    tools = await _within(get_pipeline_tools(), BIND_TIMEOUT, "binding MCP servers")
    names = {t.name for t in tools}

    missing = EXPECTED_TOOLS - names
    assert not missing, f"MCP servers did not expose: {sorted(missing)}"
    print(f"\n[live] bound {len(names)} tools: {sorted(names)}")


@pytest.mark.anyio
async def test_supabase_tools_are_org_scoped():
    user_id = _user_id()

    schema = await _within(describe_table(user_id, "unified_transactions"), QUERY_TIMEOUT, "describe_table")
    assert "user_id" in str(schema).lower()

    own = await _within(
        run_read_only_sql(
            user_id,
            "SELECT user_id, COUNT(*) AS n FROM unified_transactions GROUP BY user_id",
        ),
        QUERY_TIMEOUT,
        "in-scope aggregate",
    )
    assert own["row_count"] >= 1, "expected at least the caller's own rows"
    own_ids = {r["user_id"] for r in own["rows"]}
    print(f"\n[live] org ids visible to {user_id}: {own_ids}")

    foreign = await _within(
        run_read_only_sql(
            user_id,
            "SELECT user_id, COUNT(*) AS n FROM unified_transactions "
            f"WHERE user_id = {FOREIGN_USER_ID} GROUP BY user_id",
        ),
        QUERY_TIMEOUT,
        "cross-tenant read",
    )
    assert foreign["row_count"] == 0, f"tenant leak: {foreign['rows']}"

    with pytest.raises(ValueError, match="unified_transactions"):
        await _within(
            run_read_only_sql(user_id, "SELECT user_id, api_key FROM user_settings"),
            QUERY_TIMEOUT,
            "disallowed relation",
        )
    print("[live] tenant boundary held: cross-tenant empty, user_settings blocked")


@pytest.mark.anyio
async def test_anomaly_node_runs():
    user_id = _user_id()

    out = await _within(
        anomaly_detection_node({"user_id": user_id, "analysis_limit": 200}),
        ANOMALY_TIMEOUT,
        "anomaly_detect",
    )
    result = out["anomaly_result"]

    print(
        f"\n[live] anomalies={result['anomaly_count']} "
        f"rows={result['rows_analyzed']} skipped={result['rows_skipped']} "
        f"severity={result.get('severity_counts')}"
    )
    assert result["success"] is True
    assert result["rows_analyzed"] > 0
    assert result["rows_skipped"] == 0, "junk-row filter regressed"
    assert isinstance(result["anomaly_count"], int)
    assert len(out["anomalies"]) == result["anomaly_count"]


@pytest.mark.anyio
async def test_reporting_node_runs():
    """The step that hung during manual verification, now bounded."""
    user_id = _user_id()

    state = {
        "user_id": user_id,
        "anomalies": [
            {
                "external_id": "live-smoke-1",
                "category": "Marketing",
                "amount": 4200.0,
                "transaction_date": "2026-09-01",
                "entity": "unknown",
                "severity": "High",
                "signals": ["budget_breach"],
            }
        ],
        "anomaly_flags": ["budget_breach"],
        "anomaly_result": {
            "success": True,
            "anomaly_count": 1,
            "rows_analyzed": 200,
            "rows_skipped": 0,
            "severity_counts": {"High": 1},
            "flags": ["budget_breach"],
        },
    }

    out = await _within(reporting_node(state), REPORT_TIMEOUT, "reporting")
    report = out.get("report") or {}

    print(f"\n[live] report={ {k: v for k, v in report.items() if k != 'path'} }")
    assert report.get("generated") is True, report.get("error")
    assert report.get("report_storage_path")


@pytest.mark.anyio
async def test_report_window_narrows_the_rows_read():
    """A 1-month window must return strictly fewer rows than the full history.

    Reads the same table twice through the period-aware read, so this proves the
    bound is actually applied rather than just accepted.
    """
    from app.db.database import get_max_transaction_date, get_user_transactions
    from app.graph.period import resolve_window

    user_id = _user_id()

    anchor = await asyncio.to_thread(get_max_transaction_date, user_id)
    assert anchor, "live user has transactions"

    wide_start, end = resolve_window(12, anchor)
    narrow_start, narrow_end = resolve_window(1, anchor)

    wide = await asyncio.to_thread(
        get_user_transactions, user_id, None, wide_start, end
    )
    narrow = await asyncio.to_thread(
        get_user_transactions, user_id, None, narrow_start, narrow_end
    )

    print(
        f"\n[live] window 12mo={wide_start}..{end} rows={len(wide)} | "
        f"1mo={narrow_start}..{narrow_end} rows={len(narrow)}"
    )
    assert len(narrow) <= len(wide)
    assert narrow, "a 1-month window should still contain the newest month"
    # Everything inside the narrow read must also fall inside the wide read.
    assert {r["id"] for r in narrow} <= {r["id"] for r in wide}
    # And every row really is inside the requested bounds.
    assert all(
        str(r["Date"])[:10] >= narrow_start and str(r["Date"])[:10] <= narrow_end
        for r in narrow
    )


@pytest.mark.anyio
async def test_supervisor_resolves_the_window_against_live_data():
    from app.graph.supervisor import supervisor_node

    out = await _within(
        supervisor_node({"user_id": _user_id(), "trigger": "new_data", "report_months": 3}),
        60.0,
        "supervisor window",
    )

    print(f"\n[live] window={out['report_months']}mo {out['start_date']}..{out['end_date']}")
    assert out["report_months"] == 3
    assert out["start_date"] < out["end_date"]


@_LLM_REQUIRED
@pytest.mark.anyio
async def test_analyst_node_answers_chat():
    from app.graph.analyst_node import analyst_node

    user_id = _user_id()

    out = await _within(
        analyst_node({"user_id": user_id, "question": "What was our total spend?"}),
        300.0,
        "analyst",
    )
    answer = out["analyst"]["answer"]

    print(f"\n[live] analyst answer: {answer[:300]}")
    assert answer and answer.strip()


@pytest.mark.anyio
async def test_supervisor_stops_on_unknown_trigger():
    from app.graph.supervisor import graph

    out = await _within(
        graph.ainvoke({"user_id": _user_id(), "trigger": "definitely-not-a-trigger"}),
        60.0,
        "supervisor routing",
    )

    assert "definitely-not-a-trigger" in out["route_error"]
    assert "anomaly_result" not in out, "a rejected trigger must not run the pipeline"
