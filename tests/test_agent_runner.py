"""Tests for the deterministic CFO pipeline in app/services/agent_runner.py.

Focus: fail-fast behavior — when a mandatory step errors, the pipeline must
stop immediately and must NOT run the remaining steps (no report generation or
email from bad state).
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.agent_runner import _step_failed, run_cfo_pipeline


def test_step_failed_classifies_success_and_error():
    assert _step_failed("Success! Unified 100 rows.") is False
    assert _step_failed("No report email configured; email skipped.") is False
    assert _step_failed("Error: Expense file not found.") is True
    assert _step_failed("Analysis failed: boom") is True
    assert _step_failed("") is True


@pytest.mark.anyio
@patch("app.db.database.get_user_settings", return_value={
    "expense_url": "https://sheets/expense",
    "revenue_url": None,
    "report_email": "cfo@acme.com",
})
@patch(
    "app.agents.mcp_server.ingest_financial_data",
    new_callable=AsyncMock,
    return_value="Error: Expense file not found.",
)
async def test_pipeline_stops_when_ingest_fails(mock_ingest, mock_settings):
    with (
        patch("app.agents.mcp_server.detect_financial_anomalies", new_callable=AsyncMock) as mock_detect,
        patch("app.agents.mcp_server.generate_cfo_pdf_report", new_callable=AsyncMock) as mock_report,
        patch("app.agents.mcp_server.send_email_report") as mock_email,
    ):
        result = await run_cfo_pipeline(user_id=1)

        assert result["success"] is False
        assert result["message"].startswith("Agent run stopped at 'ingest'")
        assert result["steps"][-1]["step"] == "ingest"

        # No downstream step may run after a failed mandatory step.
        mock_detect.assert_not_called()
        mock_report.assert_not_called()
        mock_email.assert_not_called()


@pytest.mark.anyio
@patch("app.db.database.get_user_settings", return_value={
    "expense_url": "https://sheets/expense",
    "revenue_url": None,
    "report_email": "cfo@acme.com",
})
@patch(
    "app.agents.mcp_server.ingest_financial_data",
    new_callable=AsyncMock,
    return_value="Success! Unified 100 rows.",
)
@patch(
    "app.agents.mcp_server.detect_financial_anomalies",
    new_callable=AsyncMock,
    return_value="Analysis failed: no budget limits configured.",
)
async def test_pipeline_stops_when_detect_fails(mock_detect, mock_ingest, mock_settings):
    with (
        patch("app.agents.mcp_server.generate_cfo_pdf_report", new_callable=AsyncMock) as mock_report,
        patch("app.agents.mcp_server.send_email_report") as mock_email,
    ):
        result = await run_cfo_pipeline(user_id=1)

        assert result["success"] is False
        assert result["message"].startswith("Agent run stopped at 'detect'")
        assert result["steps"][-1]["step"] == "detect"

        mock_report.assert_not_called()
        mock_email.assert_not_called()


@pytest.mark.anyio
@patch("app.db.database.get_user_settings", return_value={
    "expense_url": "https://sheets/expense",
    "revenue_url": None,
    "report_email": "cfo@acme.com",
})
@patch(
    "app.agents.mcp_server.ingest_financial_data",
    new_callable=AsyncMock,
    return_value="Success! Unified 100 rows.",
)
@patch(
    "app.agents.mcp_server.detect_financial_anomalies",
    new_callable=AsyncMock,
    return_value="Analysis complete. Detected 2 high-severity budget breaches.",
)
@patch(
    "app.agents.mcp_server.generate_cfo_pdf_report",
    new_callable=AsyncMock,
    return_value="Failed: pdf library missing.",
)
async def test_pipeline_stops_when_report_fails(mock_report, mock_detect, mock_ingest, mock_settings):
    with patch("app.agents.mcp_server.send_email_report") as mock_email:
        result = await run_cfo_pipeline(user_id=1)

        assert result["success"] is False
        assert result["message"].startswith("Agent run stopped at 'report'")
        assert result["steps"][-1]["step"] == "report"

        mock_email.assert_not_called()


@pytest.mark.anyio
@patch("app.db.database.get_user_settings", return_value={
    "expense_url": "https://sheets/expense",
    "revenue_url": None,
    "report_email": "cfo@acme.com",
})
@patch(
    "app.agents.mcp_server.ingest_financial_data",
    new_callable=AsyncMock,
    return_value="Success! Unified 100 rows.",
)
@patch(
    "app.agents.mcp_server.detect_financial_anomalies",
    new_callable=AsyncMock,
    return_value="Analysis complete. Detected 2 high-severity budget breaches.",
)
@patch(
    "app.agents.mcp_server.generate_cfo_pdf_report",
    new_callable=AsyncMock,
    return_value="Success! PDF generated as uploads/executive_cfo_report_1.pdf.",
)
@patch(
    "app.agents.mcp_server.send_email_report",
    return_value="Success! Real email sent to cfo@acme.com. Gmail Message ID: 123",
)
async def test_pipeline_completes_when_all_steps_succeed(mock_email, mock_report, mock_detect, mock_ingest, mock_settings):
    result = await run_cfo_pipeline(user_id=1)
    assert result["success"] is True
    assert result["message"] == "Agent run completed."
    assert [s["step"] for s in result["steps"]] == ["ingest", "detect", "report", "email"]
    mock_email.assert_called_once()
