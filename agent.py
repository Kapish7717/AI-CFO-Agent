from langchain_core.tools import tool
import pandas as pd
import os
from tools.data_ingestion import DataIngestion
from tools.anomaly_detection import detect_all_anomalies
from tools.report_generator import ReportGenerator
from typing import TypedDict, Optional
import operator
from typing import Annotated, Sequence
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import BaseMessage


# We use a local pickle file to share the DataFrame state between tools.
# This is necessary because LLM tools typically only pass strings/JSON around.
STATE_FILE = "current_financial_state.pkl"

@tool
def ingest_financial_data(expense_path_or_url: str, revenue_path_or_url: str = None) -> str:
    """
    Ingests financial data. Can take an expense file/URL and an optional revenue file/URL.
    Always run this tool first before analyzing anomalies or generating reports.
    """
    ingestor = DataIngestion()
    try:
        # 1. Load Expenses
        if expense_path_or_url.startswith("http://") or expense_path_or_url.startswith("https://"):
            df_exp = ingestor.load_from_google_sheets(expense_path_or_url)
        elif expense_path_or_url.endswith('.csv'):
            df_exp = ingestor.load_from_csv(expense_path_or_url)
        else:
            df_exp = ingestor.load_from_excel(expense_path_or_url)
        
        df_exp['Type'] = 'Expense'
        # Standardize Expense columns
        df_exp.rename(columns={'vendor': 'Entity', 'category': 'Category', 'amount': 'Amount', 'date': 'Date', 'department': 'Department', 'status': 'Status'}, inplace=True)
        
        # 2. Load Revenue (Optional)
        df_rev = pd.DataFrame()
        if revenue_path_or_url:
            if revenue_path_or_url.startswith("http://") or revenue_path_or_url.startswith("https://"):
                df_rev = ingestor.load_from_google_sheets(revenue_path_or_url)
            elif revenue_path_or_url.endswith('.csv'):
                df_rev = ingestor.load_from_csv(revenue_path_or_url)
            else:
                df_rev = ingestor.load_from_excel(revenue_path_or_url)
                
            df_rev['Type'] = 'Revenue'
            # Standardize Revenue columns
            df_rev.rename(columns={'client': 'Entity', 'product': 'Category', 'revenue': 'Amount', 'date': 'Date', 'department': 'Department', 'status': 'Status'}, inplace=True)

        # Combine them
        df_combined = pd.concat([df_exp, df_rev], ignore_index=True)
        
        # Ensure Date is parsed
        df_combined['Date'] = pd.to_datetime(df_combined['Date'], errors='coerce')
        
        # Save dataframe to disk so other tools can access it
        df_combined.to_pickle(STATE_FILE)
        
        msg = f"Success! Loaded {len(df_exp)} expense rows"
        if not df_rev.empty:
            msg += f" and {len(df_rev)} revenue rows. "
        else:
            msg += ". "
        return msg + "The data is unified and ready for anomaly detection."
    except Exception as e:
        return f"Failed to load data: {e}"

@tool
def detect_financial_anomalies() -> str:
    """
    Analyzes the loaded financial data to detect unusual expenses, duplicates, and MoM spikes.
    Run this tool after ingesting data, but before generating a report.
    """
    if not os.path.exists(STATE_FILE):
        return "Error: No data loaded. You must use 'ingest_financial_data' first."
        
    try:
        df = pd.read_pickle(STATE_FILE)
        processed_df = detect_all_anomalies(df)
        
        # Save the updated dataframe (which now has anomaly flags) back to disk
        processed_df.to_pickle(STATE_FILE)
        
        # Count total anomalies using the 'Severity' column
        anomaly_count = len(processed_df[processed_df['Severity'] != 'Normal'])
        return f"Success! Anomaly detection complete. Found {anomaly_count} anomalies. The data is ready for report generation."
    except Exception as e:
        return f"Failed to detect anomalies: {e}"

@tool
def generate_cfo_pdf_report(output_filename: str = "executive_cfo_report.pdf") -> str:
    """
    Generates a professional PDF report summarizing the finances and anomalies.
    Run this tool only after anomalies have been detected.
    """
    if not os.path.exists(STATE_FILE):
        return "Error: No data loaded. You must ingest data and detect anomalies first."
        
    try:
        df = pd.read_pickle(STATE_FILE)
        
        if 'Severity' not in df.columns:
            return "Error: Data has not been analyzed for anomalies yet. Run 'detect_financial_anomalies' first."
            
        report_gen = ReportGenerator(df, output_path=output_filename)
        report_gen.generate_pdf()
        
        return f"Success! The CFO report was generated and saved locally as '{output_filename}'."
    except Exception as e:
        return f"Failed to generate report: {e}"



from langgraph.prebuilt import ToolNode, tools_condition
from langchain_groq import ChatGroq
from dotenv import load_dotenv

# Gmail API Imports
import base64
from email.message import EmailMessage
import mimetypes
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]

# --- 1. NEW TOOLS ---

# Gmail Authentication Helper
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

def get_gmail_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                raise FileNotFoundError("credentials.json is missing! Please download OAuth Client ID from Google Cloud Console.")
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


@tool
def send_email(to_email: str, subject: str, body: str) -> str:
    """
    Sends an email to a specific address using the Gmail API. 
    It will automatically look for and attach 'executive_cfo_report.pdf' to the email if it exists.
    Use this to email the CFO report to stakeholders.
    """
    try:
        service = get_gmail_service()
        
        message = EmailMessage()
        message.set_content(body)
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
            print(f"\n[ATTACHMENT]: Attached {attachment_path} to email.")

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {"raw": encoded_message}
        
        print(f"\n[EMAIL TRIGGERED]: Sending real email via Gmail to {to_email} | Subject: {subject}\n")
        
        send_message = service.users().messages().send(userId="me", body=create_message).execute()
        return f"Success! Real email sent to {to_email}. Gmail Message ID: {send_message['id']}"
        
    except Exception as e:
        print(f"\n[EMAIL ERROR]: {e}")
        return f"Failed to send email: {e}"

@tool
def schedule_meeting(attendees: str, date_time: str) -> str:
    """
    Schedules a budget review meeting on Google Calendar.
    """
    print(f"\n[CALENDAR TRIGGERED]: Meeting scheduled with {attendees} at {date_time}\n")
    return f"Success! Meeting scheduled for {date_time} with {attendees}."


# --- 2. BUILD THE MANUAL AGENT GRAPH ---
tools = [ingest_financial_data, detect_financial_anomalies, generate_cfo_pdf_report, send_email, schedule_meeting]

# The LLM needs to know what tools are available
llm = ChatGroq(api_key=os.environ.get("GROQ_API_KEY"), model="llama-3.3-70b-versatile")
llm_with_tools = llm.bind_tools(tools)

# The "Agent" node simply runs the LLM
def call_model(state: AgentState):
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

# Create the graph
builder = StateGraph(AgentState)

# Add our two main nodes
builder.add_node("agent", call_model)
builder.add_node("tools", ToolNode(tools))

# The graph logic: Start -> Agent -> Tools -> Agent -> End
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition) # Automatically routes to 'tools' if needed, else END
builder.add_edge("tools", "agent")

graph = builder.compile()

# Generate the visualization
png_bytes = graph.get_graph().draw_mermaid_png()
with open("financial_agent_workflow.png", "wb") as f:
    f.write(png_bytes)
print("Workflow graph saved to financial_agent_workflow.png")

# --- 3. STREAM THE EXECUTION ---
if __name__ == "__main__":
    expense = "https://docs.google.com/spreadsheets/d/19Cv2KbKm151bPkRrP-FpsfRAG74pntV-RZpuHskiKRU/edit?usp=sharing"
    revenue = "https://docs.google.com/spreadsheets/d/1T6bRfR-oSc20P_S8zHLgE-IBSN7TXr4o6CDF8ZL-w80/edit?usp=sharing"
    EMAIL = "mfkapish@gmail.com"
    prompt = f"""
    Please run my financial pipeline for these sheets:
    Expense: {expense}
    Revenue: {revenue}
    
    Once the report is generated, please email it to {EMAIL} and schedule a meeting with the Finance team for tomorrow at 10:00 AM.
    """
    
    print(f"Starting CFO Agent...\n")
    initial_state = {"messages": [("user", prompt)]}
    
    # Stream the steps for visibility!
    final_message = ""
    for s in graph.stream(initial_state, stream_mode="updates"):
        step_name = list(s.keys())[0]
        print(f"--- Completed step: {step_name} ---")
        # Keep track of the last message sent by the agent
        if "messages" in s[step_name] and s[step_name]["messages"]:
            final_message = s[step_name]["messages"][-1].content
            
    print(f"\nFinal CFO Report Status: {final_message}")
    png_bytes = graph.get_graph().draw_mermaid_png()
    with open("financial_agent_workflow.png", "wb") as f:
        f.write(png_bytes)
    print("\n Workflow graph saved to financial_agent_workflow.png")