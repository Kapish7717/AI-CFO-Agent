"""CFO agent runner.

Provides two deterministic, side-effect-safe entry points that drive the same
tools the MCP agent uses, without needing the full ReAct loop:

- ``run_cfo_pipeline`` — ingest uploaded sheets, detect anomalies/budget
  breaches, generate the executive PDF and email it to the configured address.
  Used by the dashboard "Run agent" button and the scheduled reporter.
- ``run_data_query`` — answer a free-form question about the user's uploaded
  transactions by summarizing the stored data and asking the user's configured
  LLM to answer. No tools are called, so it is safe and fast for the AI Chat.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any


async def ingest_user_data(user_id: int) -> dict[str, Any]:
    """Ingest the user's uploaded sheets and refresh budget breaches.

    Called after an upload so the dashboard reflects the new data immediately.
    """
    from app.agents.mcp_server import ingest_financial_data
    from app.services.budget_breaches import refresh_budget_breaches

    try:
        from app.db.database import get_user_settings
        settings = get_user_settings(user_id)
    except Exception as e:
        return {"success": False, "message": f"Failed to load settings: {e}"}

    expense = settings.get("expense_url") or settings.get("expense_file_path")
    revenue = settings.get("revenue_url") or settings.get("revenue_file_path")
    if not expense:
        return {"success": False, "message": "No expense data to ingest."}

    try:
        result = await ingest_financial_data(expense, revenue, user_id=user_id)
        refresh_budget_breaches(user_id)
        return {"success": True, "message": result}
    except Exception as e:
        return {"success": False, "message": f"Ingestion failed: {e}"}


def _step_failed(result: str) -> bool:
    """Return True when a tool's message indicates the step did not succeed.

    Tools in ``app.agents.mcp_server`` report failures with explicit markers
    (``"Error: ..."``, ``"Failed: ..."``, ``"Analysis failed: ..."``, timeouts)
    and successes with ``"Success! ..."`` / ``"Analysis complete. ..."``. Treat
    anything containing a failure marker as a failure so the pipeline bails out
    before chaining more steps on top of bad state (e.g. generating a report
    from empty untransformed data).
    """
    if not result:
        return True
    lower = str(result).lower()
    for marker in ("error", "failed", "failure", "timeout"):
        if marker in lower:
            return True
    return False


def _abort(
    steps: list[dict[str, Any]],
    stopped_at: str,
    reason: str,
    email: str | None = None,
) -> dict[str, Any]:
    """Build the fail-fast response with the steps executed so far."""
    return {
        "success": False,
        "steps": steps,
        "message": f"Agent run stopped at '{stopped_at}': {reason}",
        "email": email,
    }


async def run_cfo_pipeline(user_id: int, to_email: str | None = None) -> dict[str, Any]:
    """Run the full CFO workflow for a user.

    Steps: ingest financial data -> detect anomalies/budget breaches ->
    generate the executive PDF report -> send the report email.

    Fails fast: if any mandatory step returns an error, the pipeline stops
    immediately and does NOT run the remaining steps (so a report is never
    generated or emailed from empty/bad data). Only the email step is optional
    (it is skipped when no address is configured).

    ``to_email`` overrides the stored ``report_email`` when provided.
    """
    from app.agents.mcp_server import (
        detect_financial_anomalies,
        generate_cfo_pdf_report,
        ingest_financial_data,
        send_email_report,
    )
    from app.db.database import get_user_settings

    settings = get_user_settings(user_id)
    expense = settings.get("expense_url") or settings.get("expense_file_path")
    revenue = settings.get("revenue_url") or settings.get("revenue_file_path")

    if not expense:
        return {
            "success": False,
            "steps": [],
            "message": "No expense data found. Upload your financial sheets first.",
        }

    steps: list[dict[str, Any]] = []

    ingest_res = await ingest_financial_data(expense, revenue, user_id=user_id)
    steps.append({"step": "ingest", "message": ingest_res})
    if _step_failed(ingest_res):
        return _abort(steps, "ingest", "financial data ingestion failed")

    detect_res = await detect_financial_anomalies(user_id=user_id)
    steps.append({"step": "detect", "message": detect_res})
    if _step_failed(detect_res):
        return _abort(steps, "detect", "anomaly detection failed")

    report_res = await generate_cfo_pdf_report(user_id=user_id)
    steps.append({"step": "report", "message": report_res})
    if _step_failed(report_res):
        return _abort(steps, "report", "PDF report generation failed")

    email = to_email or settings.get("report_email")
    email_res = "No report email configured; email skipped."
    if email:
        subject = f"AI CFO Executive Report — {datetime.now().strftime('%b %d, %Y')}"
        body = (
            "Please find your AI CFO executive report attached.\n\n"
            "Generated automatically by the AI CFO agent."
        )
        try:
            email_res = send_email_report(email, subject, body, user_id=user_id)
        except Exception as e:
            email_res = f"Email failed: {e}"
    steps.append({"step": "email", "message": email_res})

    ok = not _step_failed(email_res)

    return {
        "success": bool(ok),
        "steps": steps,
        "message": "Agent run completed." if ok else "Agent run finished with errors.",
        "email": email,
    }


def build_data_digest(user_id: int, limit: int = 25) -> str:
    """Build a compact, human-readable digest of the user's stored transactions.

    Used to ground the AI Chat answers in the actual uploaded data.
    """
    import pandas as pd

    from app.db.database import get_user_transactions

    rows = get_user_transactions(user_id)
    if not rows:
        return "No transaction data found. Upload financial sheets first."

    df = pd.DataFrame(rows)
    if df.empty:
        return "No transaction data found. Upload financial sheets first."

    digest: list[str] = []
    digest.append(f"Total transactions: {len(df)}")

    if "Amount" in df.columns:
        digest.append(f"Total spend: ${df[df['Type'] == 'Expense']['Amount'].sum():,.2f}")
        if (df["Type"] == "Revenue").any():
            digest.append(f"Total revenue: ${df[df['Type'] == 'Revenue']['Amount'].sum():,.2f}")

    if "Category" in df.columns and "Amount" in df.columns:
        digest.append("\nSpend by category:")
        cat = df[df["Type"] == "Expense"].groupby("Category")["Amount"].sum().sort_values(ascending=False)
        for c, a in cat.head(15).items():
            digest.append(f"- {c}: ${a:,.2f}")

    if "Entity" in df.columns:
        digest.append("\nTop vendors/entities:")
        ent = df.groupby("Entity")["Amount"].sum().sort_values(ascending=False)
        for e, a in ent.head(10).items():
            digest.append(f"- {e}: ${a:,.2f}")

    if "Severity" in df.columns:
        anomalies = df[df["Severity"] != "Normal"]
        digest.append(f"\nAnomalies flagged: {len(anomalies)}")
        for _, r in anomalies.head(5).iterrows():
            digest.append(
                f"- {r.get('Date', 'N/A')} | {r.get('Type', '?')} | {r.get('Category', '?')} "
                f"| {r.get('Entity', '?')} | ${r.get('Amount', 0):,.2f} | {r.get('Severity', '?')}"
            )

    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df["Month"] = df["Date"].dt.strftime("%b %Y")
        digest.append("\nMonthly totals:")
        monthly = df.groupby("Month")["Amount"].sum().sort_index()
        for m, a in monthly.items():
            digest.append(f"- {m}: ${a:,.2f}")

    try:
        with open(f"uploads/budget_breaches_{user_id}.json") as f:
            import json
            breaches = json.load(f)
        if breaches:
            digest.append("\nActive budget breaches:")
            for b in breaches:
                digest.append(
                    f"- {b.get('Category', '?')}: spent ${b.get('Actual', 0):,.2f} "
                    f"(limit ${b.get('Limit', 0):,.2f}) | {b.get('Percent_Over', '?')} over"
                )
    except Exception:
        pass

    digest.append(f"\n--- Latest {limit} transactions ---")
    if "Date" in df.columns:
        recent = df.sort_values("Date", ascending=False).head(limit)
    else:
        recent = df.head(limit)
    for _, r in recent.iterrows():
        date_str = r["Date"].strftime("%Y-%m-%d") if "Date" in r and pd.notnull(r.get("Date")) else "N/A"
        digest.append(
            f"{date_str} | {r.get('Type', '?')} | {r.get('Category', '?')} "
            f"| {r.get('Entity', '?')} | ${r.get('Amount', 0):,.2f}"
        )

    return "\n".join(digest)


async def run_data_query(user_id: int, question: str) -> str:
    """Answer a free-form question using the user's uploaded transaction data.

    The stored data is summarized into a digest which is passed to the user's
    configured LLM (primary provider/model from settings) for a grounded answer.
    """
    from app.db.database import get_user_settings
    from app.services.llm_factory import create_llm, generate_text

    digest = build_data_digest(user_id)
    if digest.startswith("No transaction data found"):
        return digest

    settings = get_user_settings(user_id)
    provider = settings.get("llm_primary_provider") or "mock"
    model = settings.get("llm_primary_model")

    prompt = (
        "You are a financial analyst answering a user's question using ONLY the "
        "data digest below. Be precise, cite numbers, and do not invent data. "
        "If the answer is not in the digest, say so clearly.\n\n"
        f"USER QUESTION: {question}\n\n"
        f"DATA DIGEST:\n{digest}"
    )

    try:
        llm = create_llm(provider=provider, model=model, api_key=settings.get("api_key"))
    except Exception as e:
        return f"Failed to initialize LLM: {e}"

    try:
        answer = await generate_text(llm, prompt)
        if answer.startswith("[llm error]") or answer.startswith("[mock]"):
            # Return a useful fallback instead of raw mock/error text.
            return (
                "I could not compute a full answer with the current model, but here is "
                "what the data shows:\n\n" + digest
            )
        return answer
    except Exception as e:
        sys.stderr.write(f"[DATA QUERY ERROR] {e}\n")
        return f"Data query failed: {e}"
