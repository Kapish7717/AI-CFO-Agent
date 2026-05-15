from mcp.server.fastmcp import FastMCP
import os
import sys
import json
import base64
import asyncio
import mimetypes
import pandas as pd
from google_auth import get_gmail_service, get_calendar_service
from email.message import EmailMessage
from tools.data_ingestion import DataIngestion
from tools.anomaly_detection import detect_all_anomalies
from tools.report_generator import ReportGenerator

mcp = FastMCP("CFO_Central_Server")

# Configuration for shared state
STATE_FILE = "current_financial_state.pkl"

def clean_input(val):
    if not val: return None
    val = str(val).strip().strip("'").strip('"')
    if "URL:" in val:
        val = val.split("URL:")[-1].strip()
    return val

@mcp.tool()
async def ingest_financial_data(expense_path_or_url: str, revenue_path_or_url: str = None) -> str:
    """
    Ingests financial data from CSV/Excel or Google Sheets.
    Always run this first.
    """
    expense_path_or_url = clean_input(expense_path_or_url)
    revenue_path_or_url = clean_input(revenue_path_or_url)

    ingestor = DataIngestion()
    sys.stderr.write(f"[MCP] Tool 'ingest_financial_data' started. Expense: {expense_path_or_url}\n")
    try:
        if expense_path_or_url:
            is_url = expense_path_or_url.startswith("http")
            exists = os.path.exists(expense_path_or_url)
            
            if not is_url and not exists:
                return f"Error: Expense file not found at {expense_path_or_url}. Please check the path."
                
            if is_url:
                df_exp = ingestor.load_from_google_sheets(expense_path_or_url)
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
                        # If the target column (e.g. 'Amount') already exists but is mostly empty/zero
                        # while the source column (e.g. 'Revenue') has data, we prioritize the source.
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
                    if col != 'Amount': # Don't overwrite Amount if it exists but is 0 (might be legitimate)
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
                    if is_rev_url:
                        df_rev = ingestor.load_from_google_sheets(revenue_path_or_url)
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
                            
            # Use locals().get for safer access to df_rev
            df_rev_final = locals().get('df_rev')
            if df_rev_final is not None:
                df = await asyncio.to_thread(pd.concat, [df_exp, df_rev_final], ignore_index=True)
            else:
                df = df_exp
            
            # --- ROBUST CONVERSION ---
            def parse_date(date_str):
                if pd.isna(date_str) or str(date_str).strip() in ['', 'Unknown']:
                    return pd.NaT
                # Try Day-First parsing first (DD-MM-YYYY) as requested by user's data patterns
                try:
                    return pd.to_datetime(date_str, dayfirst=True)
                except:
                    try:
                        return pd.to_datetime(date_str, dayfirst=False)
                    except:
                        return pd.to_datetime(date_str, errors='coerce')

            # Apply robust parsing
            if df['Date'].dtype == object:
                df['Date'] = df['Date'].apply(parse_date)
            else:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            
            # Fill remaining NaT with a safe default (start of current year) to prevent dashboard issues
            if df['Date'].isna().any():
                default_date = pd.Timestamp.now().replace(month=1, day=1)
                df['Date'] = df['Date'].fillna(default_date)
                
            # Convert Amount to numeric
            df['Amount'] = pd.to_numeric(df['Amount'], errors='coerce').fillna(0.0)
            
            # Sort by date for a cleaner pipeline
            df = df.sort_values('Date')
            
            await asyncio.to_thread(df.to_pickle, STATE_FILE)
            return f"Success! Unified {len(df)} rows into a consistent DD-MM-YYYY format and saved to state."
        else:
            return "Error: No expense path or URL provided."
    except Exception as e:
        return f"Error during ingestion: {e}"

@mcp.tool()
async def detect_financial_anomalies(budget_limits: dict = None) -> str:
    """
    Analyzes the ingested data for budget breaches and unusual patterns.
    """
    if not os.path.exists(STATE_FILE):
        return "Error: No data loaded. Run ingest_financial_data first."
    
    sys.stderr.write("[MCP] Tool 'detect_financial_anomalies' started.\n")
    try:
        df = await asyncio.to_thread(pd.read_pickle, STATE_FILE)
        df_analyzed = await asyncio.to_thread(detect_all_anomalies, df, budget_limits=budget_limits)
        await asyncio.to_thread(df_analyzed.to_pickle, STATE_FILE)
        
        breaches = df_analyzed[df_analyzed['Severity'] == 'High']
        count = len(breaches)
        
        # Save breaches for the email tool to find
        if count > 0:
            # We only want one entry per category for the email summary
            # specifically for budget breaches
            budget_breaches = df_analyzed[df_analyzed['Is_Budget_Breach'] == True]
            if not budget_breaches.empty:
                summary = budget_breaches.drop_duplicates(subset=['Category'])
                with open("budget_breaches.json", "w") as f:
                    json.dump(summary.to_dict('records'), f, indent=2, default=str)
        else:
            if os.path.exists("budget_breaches.json"):
                os.remove("budget_breaches.json")
                
        return f"Analysis complete. Detected {count} high-severity budget breaches."
    except Exception as e:
        return f"Analysis failed: {e}"


@mcp.tool()
async def generate_cfo_pdf_report(custom_instructions: str = "") -> str:
    sys.stderr.write("[MCP DEBUG] ENTERING generate_cfo_pdf_report\n")
    """
    Generates a professional PDF report from the analyzed financial data.
    Call this immediately after detect_financial_anomalies.
    custom_instructions: Optional user requests for the report content.
    """
    output_filename = "executive_cfo_report.pdf"
    if not os.path.exists(STATE_FILE):
        return "Error: Run ingestion and analysis first."
        
    sys.stderr.write("[MCP DEBUG] STATE_FILE exists. Proceeding...\n")
    try:
        df = await asyncio.to_thread(pd.read_pickle, STATE_FILE)
        sys.stderr.write(f"[MCP DEBUG] Data loaded: {len(df)} rows. Initializing ReportGenerator...\n")
        report_gen = ReportGenerator(df, output_path=output_filename, custom_instructions=custom_instructions)
        sys.stderr.write("[MCP DEBUG] Calling generate_pdf...\n")
        await asyncio.to_thread(report_gen.generate_pdf)
        sys.stderr.write("[MCP DEBUG] generate_pdf COMPLETED.\n")
        return f"Success! PDF generated as {output_filename}."
    except Exception as e:
        return f"Failed: {e}"

@mcp.tool()
def send_email_report(to_email: str, subject: str, body: str) -> str:
    """
    Sends a CFO report email via Gmail. 
    to_email: The recipient email address.
    subject: The subject of the email.
    body: The main content of the email.
    """
    try:
        service = get_gmail_service()
        
        # Automatically check for budget breaches and mention them in the email body
        budget_warning = ""
        BREACH_FILE = "budget_breaches.json"
        if os.path.exists(BREACH_FILE):
            try:
                import json
                with open(BREACH_FILE, "r") as f:
                    breaches = json.load(f)
                if breaches:
                    budget_warning = "\n\n⚠️ URGENT: BUDGET BREACHES DETECTED\n"
                    for b in breaches:
                        budget_warning += f"- {b['Category']}: Spent ${b['Actual']:,.2f} (Limit: ${b['Limit']:,.2f}) | Over by ${b['Overspend']:,.2f} ({b['Percent_Over']})\n"
            except:
                pass

        message = EmailMessage()
        message.set_content(body + budget_warning)
        message["To"] = to_email
        message["From"] = "me"
        message["Subject"] = subject

        # Automatically attach the generated PDF report
        attachment_path = "executive_cfo_report.pdf"
        if os.path.exists(attachment_path):
            type_subtype, _ = mimetypes.guess_type(attachment_path)
            maintype, subtype = (type_subtype or "application/pdf").split("/")
            with open(attachment_path, "rb") as fp:
                message.add_attachment(fp.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(attachment_path))
            sys.stderr.write(f"\n[ATTACHMENT]: Attached {attachment_path} to email.\n")
        else:
            sys.stderr.write(f"\n[EMAIL BLOCKED]: PDF report '{attachment_path}' not found. Aborting email.\n")
            return f"Error: The PDF report has not been generated yet. You MUST call 'generate_cfo_pdf_report' before you can send it via email."

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"raw": encoded_message}
        
        sys.stderr.write(f"\n[EMAIL TRIGGERED]: Sending real email via Gmail to {to_email} | Subject: {subject}\n")
        
        send_message = service.users().messages().send(userId="me", body=create_message).execute()
        sys.stderr.write(f"[MCP] Tool 'send_email_report' completed successfully.\n")
        return f"Success! Real email sent to {to_email}. Gmail Message ID: {send_message['id']}"
        
    except Exception as e:
        sys.stderr.write(f"\n[EMAIL ERROR]: {e}\n")
        return f"Failed to send email: {e}"


@mcp.tool()
def schedule_meeting(attendees: str, start_time: str, end_time: str) -> str:
    """
    Schedules a budget review meeting on Google Calendar.
    attendees: comma-separated list of email addresses.
    start_time: ISO 8601 format date-time string for the meeting start (e.g., '2026-05-10T10:00:00'). Do NOT include timezone offsets.
    end_time: ISO 8601 format date-time string for the meeting end (e.g., '2026-05-10T11:00:00'). Do NOT include timezone offsets.
    """
    summary = "Financial Budget Review"
    try:
        service = get_calendar_service()
        
        attendee_list = [{"email": email.strip()} for email in attendees.split(",")]
        
        event = {
            'summary': summary,
            'description': 'Automated Financial Budget Review scheduled by AI CFO Agent.',
            'start': {
                'dateTime': start_time,
                'timeZone': 'Asia/Kolkata', # Defaulting to IST, can be dynamic
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



if __name__ == "__main__":
    mcp.run()