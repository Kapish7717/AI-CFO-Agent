"""Tests for reporting-mcp and the reporting LangGraph node (Step 5).

Offline: the wrapped report/dispatch implementations are monkeypatched and the
MCP tool layer is faked, so the wrappers, the instruction brief, the dispatch
gating and the state contract are exercised without generating a PDF or
touching Gmail, Calendar or Supabase Storage.
"""

import json

import pytest

from app.graph import reporting_node as node
from app.mcp.reporting import server as server


class _FakeTool:
    def __init__(self, name, result):
        self.name = name
        self.result = result
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return self.result


def _envelope(payload):
    return [{"type": "text", "text": json.dumps(payload), "id": "lc_1"}]


def _anomaly(**overrides):
    base = {
        "external_id": "ch_1",
        "amount": 80835.0,
        "transaction_date": "2026-05-01T00:00:00",
        "transaction_type": "Expense",
        "category": "Travel",
        "entity": "Wikizz",
        "severity": "High",
        "signals": ["budget_breach"],
    }
    base.update(overrides)
    return base


def _patch(monkeypatch, results, **settings):
    tools = [_FakeTool(name, _envelope(payload)) for name, payload in results.items()]
    monkeypatch.setattr(
        node, "get_pipeline_tools", lambda: _async_value(tools)
    )
    monkeypatch.setattr(
        "app.db.database.get_user_settings", lambda user_id: dict(settings)
    )
    return {t.name: t for t in tools}


async def _async_value(value):
    return value


def test_result_marks_success_and_failure():
    assert server._result("Success! PDF generated as x.pdf")["success"] is True
    assert server._result("Failed: boom")["success"] is False
    assert server._result("Error: no data")["success"] is False
    assert server._result(None)["success"] is True


@pytest.mark.anyio
async def test_reporting_server_wraps_generate(monkeypatch):
    calls = {}

    async def fake_generate(
        custom_instructions="",
        user_id=None,
        start_date=None,
        end_date=None,
        report_months=None,
    ):
        calls["args"] = {
            "custom_instructions": custom_instructions,
            "user_id": user_id,
            "start_date": start_date,
            "end_date": end_date,
            "report_months": report_months,
        }
        return f"Success! PDF generated as report_{user_id}.pdf."

    monkeypatch.setattr(
        "app.agents.mcp_server.generate_cfo_pdf_report", fake_generate, raising=True
    )

    result = await server.generate_cfo_pdf_report(user_id=4, custom_instructions="hi")

    assert result["success"] is True
    assert result["report_storage_path"] == "reports/executive_cfo_report_4.pdf"
    assert calls["args"] == {
        "custom_instructions": "hi",
        "user_id": 4,
        "start_date": None,
        "end_date": None,
        "report_months": None,
    }


@pytest.mark.anyio
async def test_reporting_server_forwards_the_report_window(monkeypatch):
    # The window has to reach the generator, otherwise the user's chosen period
    # is silently ignored and the PDF always covers 12 months.
    calls = {}

    async def fake_generate(custom_instructions="", user_id=None, start_date=None,
                            end_date=None, report_months=None):
        calls["args"] = {
            "start_date": start_date,
            "end_date": end_date,
            "report_months": report_months,
        }
        return "Success! PDF generated."

    monkeypatch.setattr(
        "app.agents.mcp_server.generate_cfo_pdf_report", fake_generate, raising=True
    )

    await server.generate_cfo_pdf_report(
        user_id=4,
        start_date="2026-07-01",
        end_date="2026-09-15",
        report_months=3,
    )

    assert calls["args"] == {
        "start_date": "2026-07-01",
        "end_date": "2026-09-15",
        "report_months": 3,
    }


@pytest.mark.anyio
async def test_reporting_server_wraps_dispatch(monkeypatch):
    async def fake_send(to_email, subject, body, user_id=None):
        return f"Success! Real email sent to {to_email}."

    async def fake_schedule(attendees, start_time, end_time, user_id=None):
        return "Success! Meeting scheduled."

    monkeypatch.setattr("app.agents.mcp_server.send_email_report", fake_send, raising=True)
    monkeypatch.setattr("app.agents.mcp_server.schedule_meeting", fake_schedule, raising=True)

    sent = await server.send_email_report(
        user_id=4, to_email="cfo@example.com", subject="s", body="b"
    )
    scheduled = await server.schedule_budget_review(
        user_id=4,
        attendees="a@b.com",
        start_time="2026-05-10T10:00:00",
        end_time="2026-05-10T11:00:00",
    )

    assert sent["success"] is True and sent["to_email"] == "cfo@example.com"
    assert scheduled["success"] is True


@pytest.mark.anyio
async def test_reporting_server_registers_expected_tools():
    tools = {t.name for t in await server.mcp.list_tools()}
    assert tools == {
        "generate_cfo_pdf_report",
        "send_email_report",
        "schedule_budget_review",
    }


def test_instructions_when_no_anomalies():
    text = node._build_instructions([], {"severity_counts": {}})

    assert "No anomalies" in text


def test_instructions_summarize_severity_and_breaches():
    text = node._build_instructions(
        [_anomaly(), _anomaly(external_id="ch_2", amount=10.0, signals=["zscore"])],
        {"severity_counts": {"High": 1, "Medium": 1}, "flags": ["budget_breach", "zscore"]},
    )

    assert "2 transactions were flagged" in text
    assert "High 1" in text and "Medium 1" in text
    assert "Largest budget breaches" in text
    assert "Travel" in text


def test_instructions_flag_low_confidence_duplicates():
    text = node._build_instructions(
        [_anomaly(entity="unknown", signals=["rule_based"])],
        {"severity_counts": {"Medium": 1}, "flags": ["rule_based"]},
    )

    assert "low confidence" in text


@pytest.mark.anyio
async def test_node_generates_and_emails(monkeypatch):
    by_name = _patch(
        monkeypatch,
        {
            "generate_cfo_pdf_report": {
                "success": True,
                "detail": "Success!",
                "report_storage_path": "reports/executive_cfo_report_7.pdf",
            },
            "send_email_report": {"success": True, "detail": "Success!"},
        },
        report_email="cfo@example.com",
    )

    out = await node.reporting_node(
        {
            "user_id": 7,
            "anomalies": [_anomaly()],
            "anomaly_result": {"anomaly_count": 1, "severity_counts": {"High": 1}, "flags": ["budget_breach"]},
        }
    )

    assert out["report"]["success"] is True
    assert out["report"]["generated"] is True
    assert out["report"]["delivered"] is True
    assert out["report"]["recipient"] == "cfo@example.com"
    # the brief handed to the generator mentions what the graph found
    brief = by_name["generate_cfo_pdf_report"].calls[0]["custom_instructions"]
    assert "1 transactions were flagged" in brief


@pytest.mark.anyio
async def test_node_prefers_state_recipient_over_settings(monkeypatch):
    by_name = _patch(
        monkeypatch,
        {
            "generate_cfo_pdf_report": {"success": True, "detail": "Success!"},
            "send_email_report": {"success": True, "detail": "Success!"},
        },
        report_email="settings@example.com",
    )

    out = await node.reporting_node({"user_id": 7, "report_email": "override@example.com"})

    assert out["report"]["recipient"] == "override@example.com"
    assert by_name["send_email_report"].calls[0]["to_email"] == "override@example.com"


@pytest.mark.anyio
async def test_node_skips_email_without_recipient(monkeypatch):
    by_name = _patch(
        monkeypatch, {"generate_cfo_pdf_report": {"success": True, "detail": "Success!"}}
    )

    out = await node.reporting_node({"user_id": 7})

    assert out["report"]["success"] is True
    assert out["report"]["delivered"] is False
    assert "send_email_report" not in by_name
    assert any(s.get("skipped") for s in out["report"]["steps"])


@pytest.mark.anyio
async def test_node_stops_when_pdf_generation_fails(monkeypatch):
    by_name = _patch(
        monkeypatch,
        {
            "generate_cfo_pdf_report": {"success": False, "detail": "Failed: no data"},
            "send_email_report": {"success": True, "detail": "Success!"},
        },
        report_email="cfo@example.com",
    )

    out = await node.reporting_node({"user_id": 7})

    assert out["report"]["success"] is False
    assert out["report"]["generated"] is False
    assert "no data" in out["report"]["error"]
    assert by_name["send_email_report"].calls == []


@pytest.mark.anyio
async def test_node_schedules_meeting_when_requested(monkeypatch):
    by_name = _patch(
        monkeypatch,
        {
            "generate_cfo_pdf_report": {"success": True, "detail": "Success!"},
            "schedule_budget_review": {"success": True, "detail": "Success!"},
        },
    )

    await node.reporting_node(
        {
            "user_id": 7,
            "meeting": {
                "attendees": "a@b.com",
                "start_time": "2026-05-10T10:00:00",
                "end_time": "2026-05-10T11:00:00",
            },
        }
    )

    assert by_name["schedule_budget_review"].calls[0]["start_time"] == "2026-05-10T10:00:00"


@pytest.mark.anyio
async def test_node_requires_user_id():
    out = await node.reporting_node({})

    assert out["report"]["success"] is False
    assert "user_id" in out["report"]["error"]
