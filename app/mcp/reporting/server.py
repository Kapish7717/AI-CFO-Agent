# ==========================================================
# reporting-mcp: FastMCP server (stdio transport)
# ==========================================================
# Thin domain wrapper over the report generation and dispatch code that already
# works in app/agents/mcp_server.py (CFO_Central_Server). The PDF content, the
# email composition and the calendar event shape all come from those
# implementations, so behavior is identical; these tools only adapt the legacy
# string returns into structured dicts and give the graph a stable contract.
#
# Known carry-over (fix with the Step 7 storage read migration): the wrapped
# PDF tool reads transactions via get_user_transactions, which is per-user and
# not org-scoped, unlike the supabase-mcp read tools.

from __future__ import annotations

# This server is a separate stdio process, so .env has to be loaded here rather
# than inherited: running it directly (mcp dev, the Inspector) has no parent
# that exported the environment.
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from app.agents import mcp_server

load_dotenv()

# The legacy reporting stack is imported here, at module load, rather than inside
# the tool bodies. FastMCP runs a tool on the server's single event loop, and
# importing that stack during a request occupies the loop for the duration, so
# the server never gets to answer. At startup it settles before serving starts.
# The module is imported rather than its names so attribute lookups stay late
# bound, which is what the tests patch.
mcp = FastMCP("reporting-mcp")


def _result(detail, **extra) -> dict:
    """Adapt a legacy string return into a structured result.

    The wrapped tools answer with "Success! ...", "Failed: ..." or
    "Error: ...", so the prefix decides the boolean.
    """
    text = str(detail if detail is not None else "").strip()
    lowered = text.lower()
    success = not (lowered.startswith("error:") or lowered.startswith("failed:"))
    return {"success": success, "detail": text, **extra}


@mcp.tool()
async def generate_cfo_pdf_report(
    user_id: int,
    custom_instructions: str = "",
    start_date: str | None = None,
    end_date: str | None = None,
    report_months: int | None = None,
) -> dict:
    """Generate the executive CFO PDF report for one user.

    Reads the user's analyzed transactions, renders the report with the user's
    configured LLM provider/model, and uploads it to Supabase Storage at
    ``reports/executive_cfo_report_{user_id}.pdf``.

    ``custom_instructions`` steers the written narrative; the reporting node
    passes a deterministic summary of the anomalies it detected.

    ``start_date`` / ``end_date`` are the inclusive ISO bounds of the period to
    report on, resolved once by the supervisor. When they are omitted the
    period falls back to the user's saved preference, or ``report_months``.
    """
    detail = await mcp_server.generate_cfo_pdf_report(
        custom_instructions=custom_instructions,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        report_months=report_months,
    )
    return _result(detail, report_storage_path=f"reports/executive_cfo_report_{user_id}.pdf")


@mcp.tool()
async def send_email_report(user_id: int, to_email: str, subject: str, body: str) -> dict:
    """Email the generated PDF report via the user's authenticated Gmail.

    The PDF must already exist (generate_cfo_pdf_report first); it is attached
    automatically, along with any budget-breach summary.
    """
    detail = await mcp_server.send_email_report(to_email=to_email, subject=subject, body=body, user_id=user_id)
    return _result(detail, to_email=to_email)


@mcp.tool()
async def schedule_budget_review(
    user_id: int, attendees: str, start_time: str, end_time: str
) -> dict:
    """Schedule the budget review on the user's primary Google Calendar.

    ``attendees`` is a comma-separated list of email addresses. ``start_time``
    and ``end_time`` are ISO 8601 local date-times without a timezone offset
    (e.g. '2026-05-10T10:00:00'); the event is created in Asia/Kolkata.
    """
    detail = await mcp_server.schedule_meeting(
        attendees=attendees, start_time=start_time, end_time=end_time, user_id=user_id
    )
    return _result(detail, attendees=attendees, start_time=start_time)


if __name__ == "__main__":
    mcp.run()
