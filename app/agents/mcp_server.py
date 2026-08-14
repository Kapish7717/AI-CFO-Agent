import asyncio
import base64
import json
import mimetypes
import os
import sys
from email.message import EmailMessage

import pandas as pd
from mcp.server.fastmcp import FastMCP

from app.integrations.google_auth import (
    exchange_code_for_token,
    get_auth_url,
    get_calendar_service,
    get_gmail_service,
    get_google_credentials,
    is_authenticated,
)
from app.tools.anomaly_detection import detect_all_anomalies
from app.tools.data_ingestion import DataIngestion
from app.tools.report_generator import ReportGenerator

mcp = FastMCP("CFO_Central_Server")

def get_user_state_paths(user_id: int):
    """Returns isolated state and report file paths for a given user."""
    # Ensure uploads folder exists
    os.makedirs("uploads", exist_ok=True)
    if user_id is not None:
        state_file = f"uploads/financial_state_{user_id}.pkl"
        report_file = f"uploads/executive_cfo_report_{user_id}.pdf"
        breaches_file = f"uploads/budget_breaches_{user_id}.json"
    else:
        state_file = "current_financial_state.pkl"
        report_file = "executive_cfo_report.pdf"
        breaches_file = "budget_breaches.json"
    return state_file, report_file, breaches_file

@mcp.tool()
async def authenticate_google(auth_code: str = None, user_id: int = None) -> str:
    """
    Handles Google OAuth authentication. 
    1. Call WITHOUT any arguments first to get the Login URL for the user.
    2. After the user provides a real code, call this again WITH the 'auth_code' argument.
    """
    if is_authenticated(user_id=user_id) and not auth_code:
        return "Success: Already authenticated with Google. You can proceed to financial steps."

    if not auth_code:
        try:
            get_google_credentials(user_id=user_id)
            return "Success: Authenticated with Google. You can proceed."
        except Exception as e:
            if "AUTH_REQUIRED" in str(e):
                url = get_auth_url()
                return (
                    "--- GOOGLE AUTH REQUIRED ---\n"
                    "Please follow these steps to log in:\n"
                    f"1. Visit this URL: {url}\n"
                    "2. Log in and allow permissions.\n"
                    "3. Copy the code from the address bar (after 'code=').\n"
                    "4. Paste that code into this chat.\n"
                )
            return f"Error during authentication: {e}"
    
    if auth_code:
        # Safety check for LLM hallucination: reject only clearly malformed codes.
        if not auth_code.strip() or len(auth_code) > 2048:
            return "ERROR: That looks like a hallucinated or invalid code. Please STOP and ask the user for the real code from their browser."

    result = exchange_code_for_token(auth_code, user_id=user_id)
    return result

def clean_input(val):
    if not val:
        return None
    val = str(val).strip().strip("'").strip('"')
    if "URL:" in val:
        val = val.split("URL:")[-1].strip()
    return val

@mcp.tool()
async def ingest_financial_data(expense_path_or_url: str, revenue_path_or_url: str = None, user_id: int = None) -> str:
    """
    Ingests financial data from CSV, Excel, or bank statement PDFs, or from Google Sheets.
    Always run this first.
    """
    expense_path_or_url = clean_input(expense_path_or_url)
    revenue_path_or_url = clean_input(revenue_path_or_url)
    
    state_file, _, _ = get_user_state_paths(user_id)

    ingestor = DataIngestion()
    sys.stderr.write(f"[MCP] Tool 'ingest_financial_data' started (User: {user_id}). Expense: {expense_path_or_url}\n")
    
    temp_exp_path = f"uploads/temp_ingest_expense_{user_id}.csv"
    temp_rev_path = f"uploads/temp_ingest_revenue_{user_id}.csv"
    
    try:
        # If the paths are Supabase URLs, download them authenticated to temp local files
        if expense_path_or_url and "supabase.co/storage/v1/object/public/cfo-agent-files/" in expense_path_or_url:
            from app.db.storage import download_from_storage
            rel_path = expense_path_or_url.split("cfo-agent-files/")[-1]
            import urllib.parse
            rel_path = urllib.parse.unquote(rel_path)
            if download_from_storage(rel_path, temp_exp_path):
                expense_path_or_url = temp_exp_path
                
        if revenue_path_or_url and "supabase.co/storage/v1/object/public/cfo-agent-files/" in revenue_path_or_url:
            from app.db.storage import download_from_storage
            rel_path = revenue_path_or_url.split("cfo-agent-files/")[-1]
            import urllib.parse
            rel_path = urllib.parse.unquote(rel_path)
            if download_from_storage(rel_path, temp_rev_path):
                revenue_path_or_url = temp_rev_path

        if expense_path_or_url:
            is_url = expense_path_or_url.startswith("http")
            exists = os.path.exists(expense_path_or_url)
            
            if not is_url and not exists:
                return f"Error: Expense file not found at {expense_path_or_url}. Please check the path."
                
            is_google_sheet = is_url and "docs.google.com/spreadsheets" in expense_path_or_url
            if is_google_sheet:
                # Need to authenticate sheets with user credentials
                creds = get_google_credentials(user_id=user_id)
                # Pass credentials to gspread reader if needed
                df_exp = ingestor.load_from_google_sheets(expense_path_or_url, credentials=creds)
            elif expense_path_or_url.lower().endswith('.pdf'):
                df_exp = ingestor.load_from_pdf(expense_path_or_url)
            else:
                if expense_path_or_url.lower().endswith(('.xlsx', '.xls')):
                    df_exp = ingestor.load_from_excel(expense_path_or_url)
                else:
                    df_exp = ingestor.load_from_csv(expense_path_or_url)
            
            df_exp['Type'] = 'Expense'
            df_exp.columns = [str(c).title().strip() for c in df_exp.columns]
            
            # Robust mapping for varying column names
            mapping = {
                'Vendor': 'Entity', 'Source': 'Entity', 'Merchant': 'Entity', 'Store': 'Entity', 'Payee': 'Entity', 'Payer': 'Entity', 'Client': 'Entity',
                'Amt': 'Amount', 'Value': 'Amount', 'Price': 'Amount', 'Cost': 'Amount', 'Total': 'Amount',
                'Income': 'Amount', 'Revenue': 'Amount', 'Sales': 'Amount', 'Cash': 'Amount',
                'Cat': 'Category', 'Type': 'Category', 'Description': 'Category', 'Item': 'Category', 'Group': 'Category', 'Product': 'Category',
                'Dt': 'Date', 'Time': 'Date', 'Timestamp': 'Date', 'Period': 'Date', 'Day': 'Date', 'Month': 'Date', 'Year': 'Date'
            }
            
            # Helper to apply mapping carefully
            def apply_robust_mapping(df):
                df.columns = [str(c).title().strip() for c in df.columns]
                for old_col, new_col in mapping.items():
                    if old_col in df.columns and old_col != new_col:
                        if new_col in df.columns:
                            source_data = pd.to_numeric(df[old_col], errors='coerce').fillna(0).sum()
                            target_data = pd.to_numeric(df[new_col], errors='coerce').fillna(0).sum()
                            if source_data != 0 and target_data == 0:
                                df.drop(columns=[new_col], inplace=True)
                                df.rename(columns={old_col: new_col}, inplace=True)
                        else:
                            df.rename(columns={old_col: new_col}, inplace=True)
                return df

            df_exp = apply_robust_mapping(df_exp)
            df_exp['Type'] = 'Expense'
            
            # Ensure required columns exist
            for col in ['Amount', 'Date', 'Category', 'Entity']:
                if col not in df_exp.columns or (col == 'Amount' and df_exp[col].sum() == 0):
                    if col != 'Amount':
                         df_exp[col] = 'Unknown'
                    elif col not in df_exp.columns:
                         df_exp[col] = 0
            
            if revenue_path_or_url:
                is_rev_url = revenue_path_or_url.startswith("http")
                rev_exists = os.path.exists(revenue_path_or_url)
                
                if not is_rev_url and not rev_exists:
                    sys.stderr.write(f"Warning: Revenue file not found at {revenue_path_or_url}. Skipping revenue ingestion.\n")
                    df = df_exp
                else:
                    is_rev_google_sheet = is_rev_url and "docs.google.com/spreadsheets" in revenue_path_or_url
                    if is_rev_google_sheet:
                        creds = get_google_credentials(user_id=user_id)
                        df_rev = ingestor.load_from_google_sheets(revenue_path_or_url, credentials=creds)
                    elif revenue_path_or_url.lower().endswith('.pdf'):
                        df_rev = ingestor.load_from_pdf(revenue_path_or_url)
                    else:
                        if revenue_path_or_url.lower().endswith(('.xlsx', '.xls')):
                            df_rev = ingestor.load_from_excel(revenue_path_or_url)
                        else:
                            df_rev = ingestor.load_from_csv(revenue_path_or_url)
                    
                    df_rev = apply_robust_mapping(df_rev)
                    df_rev['Type'] = 'Revenue'
                    
                    for col in ['Amount', 'Date', 'Category', 'Entity']:
                        if col not in df_rev.columns:
                            df_rev[col] = 0 if col == 'Amount' else 'Unknown'
                            
                    # Clean the amounts column
                    df_rev['Amount'] = pd.to_numeric(df_rev['Amount'], errors='coerce').fillna(0.0)
                    df_rev_final = df_rev[df_rev['Amount'] > 0].copy()
                    
                    # Concat expense and revenue dataframes
                    df = await asyncio.to_thread(pd.concat, [df_exp, df_rev_final], ignore_index=True)
            else:
                df = df_exp
            
            # Convert values cleanly
            df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
            
            if df['Date'].isna().any():
                default_date = pd.Timestamp.now().replace(month=1, day=1)
                df['Date'] = df['Date'].fillna(default_date)
                
            df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0.0)
            df = df.sort_values('Date')
            
            # Convert to dict records and insert into PostgreSQL transactions table.
            # Merge (append) instead of delete+reinsert so previously ingested data
            # (e.g. older months) is preserved when new periods are uploaded.
            rows = df.to_dict('records')
            try:
                from app.db.database import upsert_user_transactions
                result = await asyncio.to_thread(upsert_user_transactions, user_id, rows)
                sys.stderr.write(
                    f"[DB] Merged {result.get('inserted', 0)} new / skipped "
                    f"{result.get('skipped', 0)} existing transactions for User {user_id}.\n"
                )
            except Exception as dbe:
                sys.stderr.write(f"[DB ERROR] Ingestion to transactions table failed: {dbe}\n")
                raise dbe

            # Mirror the same rows into unified_transactions (source='excel') so
            # excel uploads and Stripe events share one canonical storage shape.
            try:
                from app.db.unified_store import merge_transactions_to_unified
                merged = await asyncio.to_thread(merge_transactions_to_unified, user_id, rows)
                sys.stderr.write(
                    f"[DB] Unified excel mirror: {merged.get('inserted', 0)} inserted / "
                    f"{merged.get('total', 0)} total for User {user_id}.\n"
                )
            except Exception as ue:
                sys.stderr.write(f"[DB ERROR] Unified excel mirror failed: {ue}\n")
            
            # Update user settings with these file paths so they display on restart!
            try:
                from app.db.database import update_user_settings
                if user_id is not None:
                    update_user_settings(user_id, {
                        "expense_file_path": expense_path_or_url if not is_url else None,
                        "expense_file_name": os.path.basename(expense_path_or_url) if not is_url else None,
                        "expense_url": expense_path_or_url if is_url else None,
                        "revenue_file_path": revenue_path_or_url if (revenue_path_or_url and not revenue_path_or_url.startswith("http")) else None,
                        "revenue_file_name": os.path.basename(revenue_path_or_url) if (revenue_path_or_url and not revenue_path_or_url.startswith("http")) else None,
                        "revenue_url": revenue_path_or_url if (revenue_path_or_url and revenue_path_or_url.startswith("http")) else None
                    })
            except Exception as se:
                sys.stderr.write(f"[DB Warning] Settings update skipped: {se}\n")

            return f"Success! Unified {len(df)} rows into a consistent DD-MM-YYYY format and saved to state."
        else:
            return "Error: No expense path or URL provided."
    except Exception as e:
        return f"Error during ingestion: {e}"
    finally:
        for path in [temp_exp_path, temp_rev_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

@mcp.tool()
async def detect_financial_anomalies(budget_limits: dict = None, user_id: int = None) -> str:
    """
    Analyzes the ingested data for budget breaches and unusual patterns.
    """
    _, _, breaches_file = get_user_state_paths(user_id)
    
    from app.db.database import get_user_transactions, update_transaction_anomalies
    rows = await asyncio.to_thread(get_user_transactions, user_id)
    
    if not rows:
        return "Error: No data loaded. Run ingest_financial_data first."
    
    # Default to the budgets saved in user settings when the agent does not
    # pass explicit budget_limits, so analysis always matches the UI config.
    if budget_limits is None:
        try:
            from app.db.database import get_user_settings
            settings = get_user_settings(user_id)
            from app.services.budget_breaches import CATEGORY_MAP
            budget_limits = {}
            for field, category in CATEGORY_MAP.items():
                try:
                    limit = float(settings.get(field)) if settings.get(field) else 0.0
                except (TypeError, ValueError):
                    limit = 0.0
                if limit > 0:
                    budget_limits[category] = limit
        except Exception as se:
            sys.stderr.write(f"[MCP] Failed to load budget limits from settings: {se}\n")
    
    sys.stderr.write(f"[MCP] Tool 'detect_financial_anomalies' started (User: {user_id}).\n")
    try:
        df = pd.DataFrame(rows)
        df_analyzed = await asyncio.to_thread(detect_all_anomalies, df, budget_limits=budget_limits)
        
        # Write analyzed anomalies back to transactions database table
        analyzed_rows = df_analyzed.to_dict('records')
        await asyncio.to_thread(update_transaction_anomalies, user_id, analyzed_rows)
        
        breaches = df_analyzed[df_analyzed['Severity'] == 'High']
        count = len(breaches)
        
        if count > 0:
            budget_breaches = df_analyzed[df_analyzed['Is_Budget_Breach']].copy()
            if not budget_breaches.empty:
                budget_breaches['MonthYear'] = budget_breaches['Date'].dt.strftime('%b %Y')
                summary = budget_breaches.drop_duplicates(subset=['Category', 'MonthYear'])
                with open(breaches_file, "w") as f:
                    json.dump(summary.to_dict('records'), f, indent=2, default=str)
                # Sync breaches to cloud storage
                from app.db.storage import upload_to_storage
                upload_to_storage(breaches_file, f"breaches/budget_breaches_{user_id}.json")
        else:
            if os.path.exists(breaches_file):
                os.remove(breaches_file)
            from app.db.storage import get_storage_client
            client = get_storage_client()
            if client:
                try:
                    client.storage.from_("cfo-agent-files").remove([f"breaches/budget_breaches_{user_id}.json"])
                except Exception:
                    pass
                
        return f"Analysis complete. Detected {count} high-severity budget breaches."
    except Exception as e:
        return f"Analysis failed: {e}"

@mcp.tool()
async def generate_cfo_pdf_report(custom_instructions: str = "", user_id: int = None) -> str:
    """
    Generates a professional PDF report from the analyzed financial data.
    Call this immediately after detect_financial_anomalies.
    custom_instructions: Optional user requests for the report content.
    """
    _, report_file, breaches_file = get_user_state_paths(user_id)
    
    # Try downloading budget breaches from Supabase Storage
    from app.db.storage import download_from_storage
    download_from_storage(f"breaches/budget_breaches_{user_id}.json", breaches_file)
    
    from app.db.database import get_user_transactions
    rows = await asyncio.to_thread(get_user_transactions, user_id)
    
    sys.stderr.write(f"[MCP DEBUG] ENTERING generate_cfo_pdf_report (User: {user_id})\n")
    if not rows:
        return "Error: Run ingestion and analysis first."
        
    sys.stderr.write("[MCP DEBUG] Data found. Proceeding...\n")
    try:
        df = pd.DataFrame(rows)
        sys.stderr.write(f"[MCP DEBUG] Data loaded: {len(df)} rows. Initializing ReportGenerator...\n")
        report_gen = ReportGenerator(df, output_path=report_file, 
                                     custom_instructions=custom_instructions, 
                                     breaches_file=breaches_file)
        sys.stderr.write("[MCP DEBUG] Calling generate_pdf...\n")
        await asyncio.to_thread(report_gen.generate_pdf)
        sys.stderr.write("[MCP DEBUG] generate_pdf COMPLETED. Syncing to Cloud Storage...\n")
        
        # Upload report to Supabase Storage
        from app.db.storage import upload_to_storage
        upload_to_storage(report_file, f"reports/executive_cfo_report_{user_id}.pdf")
        
        return f"Success! PDF generated as {report_file}."
    except Exception as e:
        return f"Failed: {e}"

@mcp.tool()
def send_email_report(to_email: str, subject: str, body: str, user_id: int = None) -> str:
    """
    Sends a CFO report email via Gmail. 
    to_email: The recipient email address.
    subject: The subject of the email.
    body: The main content of the email.
    """
    _, report_file, breaches_file = get_user_state_paths(user_id)
    
    # Try downloading the PDF report and breaches file from Supabase Storage
    from app.db.storage import download_from_storage
    download_from_storage(f"reports/executive_cfo_report_{user_id}.pdf", report_file)
    download_from_storage(f"breaches/budget_breaches_{user_id}.json", breaches_file)
    
    try:
        service = get_gmail_service(user_id=user_id)
        
        budget_warning = ""
        if os.path.exists(breaches_file):
            try:
                with open(breaches_file) as f:
                    breaches = json.load(f)
                if breaches:
                    budget_warning = "\n\n⚠️ URGENT: BUDGET BREACHES DETECTED\n"
                    for b in breaches:
                        budget_warning += f"- {b['Category']}: Spent ${b['Actual']:,.2f} (Limit: ${b['Limit']:,.2f}) | Over by ${b['Overspend']:,.2f} ({b['Percent_Over']})\n"
            except Exception as breach_err:
                sys.stderr.write(f"[EMAIL WARNING] Failed to read breaches file: {breach_err}\n")

        message = EmailMessage()
        message.set_content(body + budget_warning)
        message["To"] = to_email
        message["Subject"] = subject

        # Use the authenticated Gmail account as the sender when possible.
        try:
            profile = service.users().getProfile(userId="me").execute()
            sender_email = profile.get("emailAddress") or "me"
            message["From"] = sender_email
            sys.stderr.write(f"[EMAIL DEBUG] Sending from authenticated Gmail account: {sender_email}\n")
        except Exception as profile_err:
            message["From"] = "me"
            sys.stderr.write(f"[EMAIL WARNING] Could not resolve Gmail profile: {profile_err}\n")

        attachment_path = report_file
        if os.path.exists(attachment_path):
            type_subtype, _ = mimetypes.guess_type(attachment_path)
            maintype, subtype = (type_subtype or "application/pdf").split("/")
            with open(attachment_path, "rb") as fp:
                message.add_attachment(fp.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(attachment_path))
            sys.stderr.write(f"\n[ATTACHMENT]: Attached {attachment_path} to email.\n")
        else:
            sys.stderr.write(f"\n[EMAIL BLOCKED]: PDF report '{attachment_path}' not found. Aborting email.\n")
            return "Error: The PDF report has not been generated yet. You MUST call 'generate_cfo_pdf_report' before you can send it via email."

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"raw": encoded_message}

        sys.stderr.write(f"\n[EMAIL TRIGGERED]: Sending email via Gmail to {to_email} | Subject: {subject}\n")
        try:
            send_message = service.users().messages().send(userId="me", body=create_message).execute()
            sys.stderr.write(f"[MCP] Tool 'send_email_report' completed successfully. Gmail response: {send_message}\n")
            message_id = send_message.get("id")
            return f"Success! Real email sent to {to_email}. Gmail Message ID: {message_id}"
        except Exception as send_err:
            sys.stderr.write(f"[EMAIL ERROR] Failed to send Gmail message: {send_err}\n")
            return f"Failed to send email: {send_err}"
        
    except Exception as e:
        sys.stderr.write(f"\n[EMAIL ERROR]: {e}\n")
        return f"Failed to send email: {e}"

@mcp.tool()
def schedule_meeting(attendees: str, start_time: str, end_time: str, user_id: int = None) -> str:
    """
    Schedules a budget review meeting on Google Calendar.
    attendees: comma-separated list of email addresses.
    start_time: ISO 8601 format date-time string for the meeting start (e.g., '2026-05-10T10:00:00'). Do NOT include timezone offsets.
    end_time: ISO 8601 format date-time string for the meeting end (e.g., '2026-05-10T11:00:00'). Do NOT include timezone offsets.
    """
    summary = "Financial Budget Review"
    try:
        service = get_calendar_service(user_id=user_id)
        
        attendee_list = [{"email": email.strip()} for email in attendees.split(",")]
        
        event = {
            'summary': summary,
            'description': 'Automated Financial Budget Review scheduled by AI CFO Agent.',
            'start': {
                'dateTime': start_time,
                'timeZone': 'Asia/Kolkata',
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'Asia/Kolkata',
            },
            'attendees': attendee_list,
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 10},
                ],
            },
        }

        sys.stderr.write(f"\n[CALENDAR TRIGGERED]: Scheduling meeting '{summary}' on {start_time} with {attendees}\n")
        
        event = service.events().insert(calendarId='primary', body=event, sendUpdates='all').execute()
        return f"Success! Meeting scheduled. Event Link: {event.get('htmlLink')}"
        
    except Exception as e:
        sys.stderr.write(f"\n[CALENDAR ERROR]: {e}\n")
        return f"Failed to schedule meeting: {e}"

@mcp.tool()
async def query_financial_data(
    search_query: str = None,
    category: str = None,
    entity: str = None,
    transaction_type: str = None,
    start_date: str = None,
    end_date: str = None,
    limit: int = 50,
    user_id: int = None
) -> str:
    """
    Queries the user's ingested financial transactions database.
    Use this tool when the user asks specific questions about transactions, balances, spending, categories, merchants, or dates.
    search_query: a case-insensitive search term matching Category or Entity.
    category: filter by Category name.
    entity: filter by Entity name.
    transaction_type: 'Expense' or 'Revenue'.
    start_date: YYYY-MM-DD filter start.
    end_date: YYYY-MM-DD filter end.
    limit: max rows to return (default 50).
    """
    from app.db.database import get_user_transactions
    rows = await asyncio.to_thread(get_user_transactions, user_id)
    if not rows:
        return "No transaction data found. The user needs to ingest financial data first."

    df = pd.DataFrame(rows)
    
    # Apply filters
    if transaction_type:
        df = df[df['Type'].str.lower() == transaction_type.lower()]
        
    if category:
        df = df[df['Category'].str.contains(category, case=False, na=False)]
        
    if entity:
        df = df[df['Entity'].str.contains(entity, case=False, na=False)]
        
    if search_query:
        mask = (
            df['Category'].str.contains(search_query, case=False, na=False) |
            df['Entity'].str.contains(search_query, case=False, na=False) |
            df['Anomaly_Reason'].str.contains(search_query, case=False, na=False)
        )
        df = df[mask]
        
    if start_date:
        try:
            df = df[df['Date'] >= pd.to_datetime(start_date)]
        except Exception:
            pass
            
    if end_date:
        try:
            df = df[df['Date'] <= pd.to_datetime(end_date)]
        except Exception:
            pass

    total_count = len(df)
    df = df.sort_values('Date', ascending=False).head(limit)
    
    if df.empty:
        return "No transactions matched the criteria."

    # Format output
    output = [f"Found {total_count} matching transactions (showing top {len(df)}):"]
    for _, r in df.iterrows():
        date_str = r['Date'].strftime('%Y-%m-%d') if pd.notnull(r['Date']) else 'N/A'
        anomaly_flag = f" [ANOMALY: {r['Severity']}]" if r['Severity'] != 'Normal' else ""
        output.append(
            f"- {date_str} | {r['Type']} | {r['Category']} | {r['Entity']} | ${r['Amount']:,.2f}{anomaly_flag}"
        )
        
    return "\n".join(output)

if __name__ == "__main__":
    mcp.run()
