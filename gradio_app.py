import gradio as gr
import httpx
import json
import os
import pandas as pd
import matplotlib.pyplot as plt
import time

# Backend API URL (FastAPI)
API_URL = "http://localhost:8000/stream"

# Custom CSS for a beautiful, modern look
css = """
/* Import Outfit and Inter Font */
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;700;800&family=Inter:wght@400;500;600;700&display=swap');

/* Default Style Variables (matching Soft Blue) */
.gradio-container {
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
    --primary-50: #eff6ff;
    --primary-100: #dbeafe;
    --primary-200: #bfdbfe;
    --primary-300: #93c5fd;
    --primary-400: #60a5fa;
    --primary-500: #3b82f6;
    --primary-600: #2563eb;
    --primary-700: #1d4ed8;
    --primary-800: #1e40af;
    --primary-900: #1e3a8a;
    --primary-950: #172554;
    --body-background-fill: #f8fafc;
    --background-fill-primary: #ffffff;
    --background-fill-secondary: #f1f5f9;
    --border-color-primary: #e2e8f0;
}

/* Theme variables mapping */
.theme-soft {
    --primary-50: #eff6ff;
    --primary-100: #dbeafe;
    --primary-200: #bfdbfe;
    --primary-300: #93c5fd;
    --primary-400: #60a5fa;
    --primary-500: #3b82f6;
    --primary-600: #2563eb;
    --primary-700: #1d4ed8;
    --primary-800: #1e40af;
    --primary-900: #1e3a8a;
    --primary-950: #172554;
    --body-background-fill: #f8fafc;
    --background-fill-primary: #ffffff;
    --background-fill-secondary: #f1f5f9;
    --border-color-primary: #e2e8f0;
}

.theme-midnight {
    --primary-50: #faf5ff;
    --primary-100: #f3e8ff;
    --primary-200: #e9d5ff;
    --primary-300: #d8b4fe;
    --primary-400: #c084fc;
    --primary-500: #a855f7;
    --primary-600: #9333ea;
    --primary-700: #7e22ce;
    --primary-800: #6b21a8;
    --primary-900: #581c87;
    --primary-950: #3b0764;
    --body-background-fill: #0b071a;
    --background-fill-primary: #150f2b;
    --background-fill-secondary: #1f173d;
    --border-color-primary: #2e1f57;
    --block-border-color: #2e1f57;
    --neutral-50: #f5f3ff;
    --neutral-100: #ede9fe;
    --neutral-200: #ddd6fe;
    --neutral-300: #c084fc;
    --neutral-400: #a78bfa;
    --neutral-500: #8b5cf6;
    --neutral-600: #7c3aed;
    --neutral-700: #6d28d9;
    --neutral-800: #1a1033;
    --neutral-900: #120b24;
    --neutral-950: #090514;
}

.theme-emerald {
    --primary-50: #f0fdf4;
    --primary-100: #dcfce7;
    --primary-200: #bbf7d0;
    --primary-300: #86efac;
    --primary-400: #4ade80;
    --primary-500: #10b981;
    --primary-600: #059669;
    --primary-700: #047857;
    --primary-800: #065f46;
    --primary-900: #064e3b;
    --primary-950: #022c22;
    --body-background-fill: #fcfdfd;
    --background-fill-primary: #ffffff;
    --background-fill-secondary: #f0fdf4;
    --border-color-primary: #d1fae5;
}

.theme-amber {
    --primary-50: #fffbeb;
    --primary-100: #fef3c7;
    --primary-200: #fde68a;
    --primary-300: #fcd34d;
    --primary-400: #fbbf24;
    --primary-500: #f59e0b;
    --primary-600: #d97706;
    --primary-700: #b45309;
    --primary-800: #92400e;
    --primary-900: #78350f;
    --primary-950: #451a03;
    --body-background-fill: #fdfbf7;
    --background-fill-primary: #ffffff;
    --background-fill-secondary: #fef3c7;
    --border-color-primary: #fef3c7;
}

.theme-ocean {
    --primary-50: #f0f9ff;
    --primary-100: #e0f2fe;
    --primary-200: #bae6fd;
    --primary-300: #7dd3fc;
    --primary-400: #38bdf8;
    --primary-500: #0ea5e9;
    --primary-600: #0284c7;
    --primary-700: #0369a1;
    --primary-800: #075985;
    --primary-900: #0c4a6e;
    --primary-950: #082f49;
    --body-background-fill: #f0f9ff;
    --background-fill-primary: #ffffff;
    --background-fill-secondary: #e0f2fe;
    --border-color-primary: #e0f2fe;
}

/* Base Styles overrides */
.gradio-container {
    background-color: var(--body-background-fill) !important;
    transition: background-color 0.4s ease, color 0.4s ease;
}

/* Premium Navbar Header */
#navbar {
    background: linear-gradient(135deg, var(--primary-900) 0%, var(--primary-800) 100%) !important;
    padding: 1.25rem 2rem !important;
    border-radius: 20px !important;
    margin-bottom: 2rem !important;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.05) !important;
    display: flex !important;
    align-items: center !important;
    border: 1px solid rgba(255, 255, 255, 0.1) !important;
}

.brand {
    display: flex !important;
    align-items: center !important;
    gap: 1.25rem !important;
}

.brand-logo {
    font-size: 2.75rem !important;
    background: rgba(255, 255, 255, 0.15) !important;
    padding: 0.5rem !important;
    border-radius: 12px !important;
    border: 1px solid rgba(255, 255, 255, 0.2) !important;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05) !important;
}

.brand-title {
    font-family: 'Outfit', sans-serif !important;
    font-size: 2.2rem !important;
    font-weight: 800 !important;
    color: white !important;
    margin: 0 !important;
    line-height: 1.1 !important;
    letter-spacing: -0.03em !important;
}

.brand-subtitle {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.95rem !important;
    color: var(--primary-200) !important;
    margin: 0.25rem 0 0 0 !important;
    font-weight: 500 !important;
}

#theme-column {
    display: flex !important;
    align-items: center !important;
    justify-content: flex-end !important;
}

#theme-dropdown {
    width: 100% !important;
    max-width: 220px !important;
    background: rgba(255, 255, 255, 0.1) !important;
    border: 1px solid rgba(255, 255, 255, 0.2) !important;
    border-radius: 10px !important;
    color: white !important;
}

#theme-dropdown label span {
    color: var(--primary-200) !important;
    font-weight: 600 !important;
    font-size: 0.8rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}

#theme-dropdown select {
    background-color: var(--primary-900) !important;
    color: white !important;
}

/* Sidebar and Panel Enhancements */
.sidebar-panel {
    background-color: var(--background-fill-secondary) !important;
    border: 1px solid var(--border-color-primary) !important;
    border-radius: 18px !important;
    padding: 1.75rem !important;
    box-shadow: 0 4px 15px -3px rgba(0, 0, 0, 0.04) !important;
    transition: background-color 0.4s ease, border-color 0.4s ease !important;
}

/* Metric Card Layouts */
.metric-card {
    background: var(--background-fill-primary) !important;
    border: 1px solid var(--border-color-primary) !important;
    padding: 1.75rem !important;
    border-radius: 18px !important;
    box-shadow: 0 10px 20px -5px rgba(0, 0, 0, 0.03) !important;
    text-align: center !important;
    border-top: 4px solid var(--primary-500) !important;
    transition: transform 0.25s ease, box-shadow 0.25s ease, background-color 0.4s ease, border-color 0.4s ease !important;
}

.metric-card:hover {
    transform: translateY(-5px) !important;
    box-shadow: 0 20px 30px -10px rgba(0, 0, 0, 0.08) !important;
}

.metric-value {
    font-family: 'Outfit', sans-serif !important;
    font-size: 2.3rem !important;
    font-weight: 800 !important;
    color: var(--primary-900) !important;
    transition: color 0.4s ease !important;
}

.theme-midnight .metric-value {
    color: var(--primary-200) !important;
}

.metric-title {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    color: var(--neutral-500) !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    margin-top: 0.5rem !important;
}

.theme-midnight .metric-title {
    color: #a78bfa !important;
}

/* Beautiful custom slider and inputs */
input[type="range"] {
    accent-color: var(--primary-500) !important;
}

/* Tabs customization */
button[role="tab"] {
    font-family: 'Outfit', sans-serif !important;
    font-weight: 700 !important;
    font-size: 1.05rem !important;
    padding: 0.75rem 1.5rem !important;
    transition: color 0.3s ease, border-color 0.3s ease !important;
}

button[role="tab"][aria-selected="true"] {
    color: var(--primary-600) !important;
    border-bottom-color: var(--primary-600) !important;
}

.theme-midnight button[role="tab"][aria-selected="true"] {
    color: var(--primary-300) !important;
    border-bottom-color: var(--primary-300) !important;
}

/* Action button styling */
button.primary {
    background: linear-gradient(135deg, var(--primary-600) 0%, var(--primary-700) 100%) !important;
    color: white !important;
    border: none !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    box-shadow: 0 4px 10px rgba(37, 99, 235, 0.2) !important;
    transition: all 0.2s ease !important;
}

button.primary:hover {
    background: linear-gradient(135deg, var(--primary-500) 0%, var(--primary-600) 100%) !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 15px rgba(37, 99, 235, 0.3) !important;
}

button.secondary {
    background: var(--background-fill-primary) !important;
    border: 1px solid var(--border-color-primary) !important;
    color: var(--primary-700) !important;
    border-radius: 12px !important;
    font-weight: 600 !important;
    transition: all 0.2s ease !important;
}

.theme-midnight button.secondary {
    border: 1px solid var(--primary-800) !important;
    color: var(--primary-300) !important;
    background: var(--background-fill-secondary) !important;
}

button.secondary:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.05) !important;
}
"""

# Beautiful Theme Setup
theme = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="indigo",
    neutral_hue="slate"
).set(
    button_primary_background_fill="*primary_600",
    button_primary_background_fill_hover="*primary_700",
    block_title_text_weight="600",
    block_border_width="1px",
    block_shadow="*shadow_sm",
    slider_color="*primary_600",
)

def respond(message, chat_history, expense_file, expense_url, revenue_file, revenue_url, budget_marketing, budget_operations, budget_travel):
    # Construct the prompt with optional context from the sidebar
    full_prompt = message
    
    # Add Budget Context
    budget_context = f"\n\nBUDGET_LIMITS:\n- Marketing: ${budget_marketing}\n- Operations: ${budget_operations}\n- Travel: ${budget_travel}"
    full_prompt += budget_context
    
    if expense_file:
        full_prompt += f"\n\nEXPENSE_FILE_PATH: {expense_file}"
    elif expense_url:
        full_prompt += f"\n\nEXPENSE_SHEET_URL: {expense_url}"
        
    if revenue_file:
        full_prompt += f"\n\nREVENUE_FILE_PATH: {revenue_file}"
    elif revenue_url:
        full_prompt += f"\n\nREVENUE_SHEET_URL: {revenue_url}"
        
    print(f"[FRONTEND] Constructing prompt: {full_prompt}")
        
    # The agent will extract target_email directly from the chat message if provided.

    chat_history.append({"role": "user", "content": message})
    chat_history.append({"role": "assistant", "content": ""})
    bot_message = ""
    
    # Track steps for the "Agent Execution Steps" panel
    steps_list = []
    
    def get_step_emoji(tool_name):
        mapping = {
            "ingest_financial_data": "📥 Data Ingestion",
            "detect_financial_anomalies": "🔍 Anomaly Detection",
            "generate_cfo_pdf_report": "📄 PDF Report Generation",
            "send_email_report": "📧 Email Dispatch",
            "schedule_meeting": "📅 Calendar Scheduling"
        }
        return mapping.get(tool_name, f"⚙️ {tool_name}")

    try:
        # Stream response from FastAPI backend
        with httpx.stream("POST", API_URL, json={"prompt": full_prompt}, timeout=300.0) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        step_name = data.get("step")
                        msg_content = data.get("message")
                        
                        # Process Tool execution for the "Steps" panel
                        if step_name == "tools":
                            # We check if it's a success message from a tool
                            if msg_content and ("Success" in msg_content or "Successfully" in msg_content or "complete" in msg_content):
                                # Try to identify which tool just finished (this is a bit heuristic based on content)
                                if "Loaded" in msg_content: display_name = "Financial data ingested"
                                elif "Anomaly" in msg_content: display_name = "Anomaly detection complete"
                                elif "generated" in msg_content: display_name = "PDF report generated"
                                elif "Sent" in msg_content or "Executed successfully" in msg_content: display_name = "Email sent"
                                elif "Scheduled" in msg_content or "Calendar" in msg_content: display_name = "Meeting scheduled"
                                else: display_name = "Action completed"
                                
                                steps_list.append(f"✅ **{display_name}**")
                            else:
                                # Show currently executing tool
                                current_tool = "Executing action..."
                                steps_list.append(f"⏳ {current_tool}")
                        
                        # Update the bot message with real content or status
                        if step_name == "agent" and msg_content:
                            bot_message = msg_content
                        
                        # Format the steps markdown
                        if not steps_list:
                            steps_markdown = "⏳ **Agent is starting...**"
                        else:
                            # Clean up duplicates/intermediate states in steps_list
                            cleaned_steps = []
                            for s in steps_list:
                                if s.startswith("✅"):
                                    # If we find a checkmark, remove the preceding "⏳" for that same action if possible
                                    if cleaned_steps and cleaned_steps[-1].startswith("⏳"):
                                        cleaned_steps.pop()
                                    cleaned_steps.append(s)
                                elif s.startswith("⏳"):
                                    if not cleaned_steps or not cleaned_steps[-1].startswith("⏳"):
                                        cleaned_steps.append(s)
                            steps_markdown = "\n".join(cleaned_steps)
                        
                        display_text = bot_message if bot_message else "🧠 **Agent is thinking...**"
                        chat_history[-1]["content"] = display_text
                        
                        yield "", chat_history, gr.update(visible=False), steps_markdown
                    except json.JSONDecodeError:
                        pass
    except Exception as e:
        chat_history[-1]["content"] = f"❌ **Connection Error:** {e}\n\nMake sure the FastAPI backend is running via `uvicorn api:app --reload` on http://localhost:8000"
        yield "", chat_history, gr.update(visible=False), "❌ Execution failed."
        return

    # Check for the generated PDF and present it for download
    pdf_path = "executive_cfo_report.pdf"
    final_steps = "\n".join([s for s in steps_list if s.startswith("✅")])
    if os.path.exists(pdf_path):
        yield "", chat_history, gr.update(value=pdf_path, visible=True), final_steps
    else:
        yield "", chat_history, gr.update(visible=False), final_steps

def refresh_dashboard():
    STATE_FILE = "current_financial_state.pkl"
    if not os.path.exists(STATE_FILE):
        return "$0.00", "0", "N/A", "$0.00", None, "No reports generated yet."
    
    try:
        df = pd.read_pickle(STATE_FILE)
        expenses = df[df['Type'] == 'Expense'] if 'Type' in df.columns else df
        revenue = df[df['Type'] == 'Revenue'] if 'Type' in df.columns else pd.DataFrame()
        
        # 1. Total spend
        spend_num = expenses['Amount'].sum() if not expenses.empty else 0
        total_spend = f"${spend_num:,.2f}"
        
        # 2. Burn Rate (Total Expenses - Total Revenue)
        rev_num = revenue['Amount'].sum() if not revenue.empty else 0
        burn_num = spend_num - rev_num
        burn_rate = f"${burn_num:,.2f}"
        
        # 3. Anomalies detected count
        anomalies_count = str(len(df[df['Severity'] != 'Normal'])) if 'Severity' in df.columns else "0"
        
        # 3. Top spending category
        top_cat = expenses.groupby('Category')['Amount'].sum().idxmax() if not expenses.empty else "N/A"
        
        # 4. Month-over-month change chart
        fig = plt.figure(figsize=(10, 4))
        if not expenses.empty and 'Date' in expenses.columns and not expenses['Date'].isna().all():
            monthly_exp = expenses.set_index('Date').resample('ME')['Amount'].sum()
            monthly_exp.plot(kind='line', marker='o', color='#3b82f6', linewidth=2)
            plt.title('Month-over-Month Expenses', fontweight='bold')
            plt.ylabel('Amount ($)')
            plt.xlabel('')
            plt.grid(True, linestyle='--', alpha=0.7)
            plt.tight_layout()
        else:
            plt.text(0.5, 0.5, "No temporal data available", ha='center', va='center')
        
        # 5. Last report sent timestamp
        pdf_path = "executive_cfo_report.pdf"
        if os.path.exists(pdf_path):
            mod_time = os.path.getmtime(pdf_path)
            last_sent = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mod_time))
        else:
            last_sent = "Never"
            
        return total_spend, anomalies_count, str(top_cat), burn_rate, fig, last_sent
    except Exception as e:
        return "Error", "Error", "Error", "Error", None, f"Error: {e}"

def get_monthly_details(month_name):
    """Filters data for a specific month and returns metrics + charts."""
    STATE_FILE = "current_financial_state.pkl"
    if not os.path.exists(STATE_FILE) or not month_name:
        return "$0.00", "$0.00", "$0.00", None
    
    try:
        df = pd.read_pickle(STATE_FILE)
        df['MonthYear'] = df['Date'].dt.strftime('%b %Y').fillna('Unknown Date')
        
        month_df = df[df['MonthYear'] == month_name]
        expenses = month_df[month_df['Type'] == 'Expense']
        revenue = month_df[month_df['Type'] == 'Revenue']
        
        spend = expenses['Amount'].sum()
        rev = revenue['Amount'].sum()
        profit = rev - spend
        
        # Month-specific Chart: Category Breakdown
        fig = plt.figure(figsize=(10, 5))
        if not expenses.empty:
            exp_cat = expenses.groupby('Category')['Amount'].sum().sort_values(ascending=False).head(8)
            exp_cat.plot(kind='bar', color='#e74c3c')
            plt.title(f'Spending Breakdown - {month_name}', fontweight='bold')
            plt.ylabel('Amount ($)')
            plt.xticks(rotation=45)
            plt.tight_layout()
        else:
            plt.text(0.5, 0.5, f"No expense data for {month_name}", ha='center', va='center')
            
        return f"${spend:,.2f}", f"${rev:,.2f}", f"${profit:,.2f}", fig
    except Exception as e:
        print(f"Error in get_monthly_details: {e}")
        return "$0.00", "$0.00", "$0.00", None

def get_available_months(num_months):
    """Returns a list of the last N months available in the data."""
    STATE_FILE = "current_financial_state.pkl"
    if not os.path.exists(STATE_FILE):
        return []
    try:
        df = pd.read_pickle(STATE_FILE)
        if 'Date' not in df.columns or df['Date'].isna().all():
            return []
        
        # Get unique months, sorted descending
        df['MonthSort'] = df['Date'].dt.to_period('M')
        month_series = df.sort_values('Date', ascending=False)['Date'].dt.strftime('%b %Y')
        months = month_series.dropna().unique().tolist()
        if month_series.isna().any():
            months.append('Unknown Date')
        return months[:num_months]
    except:
        return []

def update_overview(num_months):
    spend, anom, cat, burn, fig, time_str = refresh_dashboard()
    months = get_available_months(num_months)
    
    spend_html = f"<div class='metric-value'>{spend}</div><div class='metric-title'>Total Expenses</div>"
    anom_html = f"<div class='metric-value'>{anom}</div><div class='metric-title'>Anomalies</div>"
    burn_html = f"<div class='metric-value'>{burn}</div><div class='metric-title'>Burn Rate</div>"
    
    # Update the selector choices
    selector_update = gr.update(choices=months, value=months[0] if months else None)
    return spend_html, anom_html, burn_html, fig, time_str, selector_update

def update_monthly_view(month_name):
    spend, rev, profit, fig = get_monthly_details(month_name)
    return spend, rev, profit, fig

def check_auth_status():
    try:
        response = httpx.get("http://localhost:8000/auth/status")
        authenticated = response.json().get("authenticated", False)
        if authenticated:
            status_markdown = """### 🟢 Status: Authenticated

Your Google account is connected and authorized. The agent has access to Gmail, Calendar, and Sheets. 

If you want to re-authenticate or switch accounts, you can use the button below."""
            return status_markdown, gr.update(visible=True), gr.update(visible=False)
        else:
            status_markdown = """### 🔴 Status: Not Authenticated

Google services are currently disconnected. You need to authorize the application to enable email, calendar scheduling, and sheets integration.

1. Click **Get Login Link 🔗** below.
2. In the new tab, sign in and authorize the application.
3. The page will redirect and automatically complete authentication in the background."""
            return status_markdown, gr.update(visible=True), gr.update(visible=True)
    except Exception as e:
        return f"### ⚠️ Status: Connection Error\n\nCould not reach the backend server: {e}", gr.update(visible=False), gr.update(visible=False)

def get_auth_link():
    try:
        response = httpx.get("http://localhost:8000/auth/url")
        url = response.json().get("url")
        link_markdown = f"### 🔗 [Click here to Login with Google]({url})\n\n1. Click the link above to open the authentication page in a new tab.\n2. Authorize the application.\n3. Once you see the \"Authentication Successful\" message, return to this dashboard.\n4. If the automatic redirect doesn't work (e.g., cloud hosting firewalls), open the **Manual Authentication Fallback** section below and paste the code."
        return link_markdown, gr.update(visible=True)
    except Exception as e:
        return f"❌ Error retrieving login link: {e}", gr.update(visible=False)

def submit_auth_code(code):
    try:
        response = httpx.post("http://localhost:8000/auth/exchange", json={"code": code})
        return response.json().get("message")
    except Exception as e:
        return f"❌ Error: {e}"

with gr.Blocks(title="AI CFO Agent", theme=theme, css=css) as demo:
    # Header Navbar
    with gr.Row(elem_id="navbar"):
        with gr.Column(scale=4, min_width=300):
            gr.HTML("""
            <div class="brand">
                <span class="brand-logo">💼</span>
                <div>
                    <h1 class="brand-title">Autonomous AI CFO</h1>
                    <p class="brand-subtitle">Your personal executive financial intelligence agent</p>
                </div>
            </div>
            """)
        with gr.Column(scale=1, min_width=150, elem_id="theme-column"):
            theme_selector = gr.Dropdown(
                choices=["Soft Blue", "Midnight Purple", "Emerald Forest", "Amber Warm", "Ocean Breeze"],
                value="Soft Blue",
                label="Select Theme Color",
                interactive=True,
                show_label=True,
                elem_id="theme-dropdown"
            )
            
    # Theme switching JS logic
    theme_js = """
    (themeName) => {
        const themeMap = {
            "Soft Blue": "theme-soft",
            "Midnight Purple": "theme-midnight",
            "Emerald Forest": "theme-emerald",
            "Amber Warm": "theme-amber",
            "Ocean Breeze": "theme-ocean"
        };
        const themeClass = themeMap[themeName] || "theme-soft";
        const container = document.querySelector('.gradio-container');
        if (container) {
            container.classList.remove('theme-soft', 'theme-midnight', 'theme-emerald', 'theme-amber', 'theme-ocean');
            container.classList.add(themeClass);
        }
        return themeName;
    }
    """
    theme_selector.change(fn=None, inputs=[theme_selector], outputs=None, js=theme_js)
    
    # Pre-define dashboard components
    month_slider = gr.Slider(label="Months to View", minimum=1, maximum=10, step=1, value=5, render=False)
    month_selector = gr.Radio(label="Select Month", choices=[], interactive=True, render=False)
    val_spend = gr.HTML(value="<div class='metric-value'>$0.00</div><div class='metric-title'>Total Expenses</div>", render=False)
    val_anom = gr.HTML(value="<div class='metric-value'>0</div><div class='metric-title'>Anomalies</div>", render=False)
    val_burn = gr.HTML(value="<div class='metric-value'>$0.00</div><div class='metric-title'>Burn Rate</div>", render=False)
    plot_trend = gr.Plot(label="Overall Expense Trend", render=False)
    val_time = gr.Textbox(label="Last Data Sync", interactive=False, value="Never", render=False)

    with gr.Tabs():
        # --- TAB 1: Chat Agent ---
        with gr.Tab("💬 Chat Agent"):
            with gr.Row():
                # Left Sidebar (Parameters)
                with gr.Column(scale=1, elem_classes=["sidebar-panel"]):
                    gr.Markdown("### ⚙️ Parameters")
                    expense_file = gr.File(label="Upload Expense CSV", file_types=[".csv"])
                    gr.Markdown("*OR*")
                    expense_url = gr.Textbox(label="Expense Google Sheets URL", placeholder="https://docs.google.com/...")
                    
                    gr.Markdown("---")
                    revenue_file = gr.File(label="Upload Revenue CSV", file_types=[".csv"])
                    gr.Markdown("*OR*")
                    revenue_url = gr.Textbox(label="Revenue Google Sheets URL", placeholder="https://docs.google.com/...")
                    
                    gr.Markdown("---")
                    gr.Markdown("### 💰 Budget Limits")
                    budget_marketing = gr.Number(label="Marketing Budget ($)", value=5000)
                    budget_operations = gr.Number(label="Operations Budget ($)", value=8000)
                    budget_travel = gr.Number(label="Travel Budget ($)", value=2000)
                    
                    pdf_download = gr.File(label="📄 Download CFO Report", visible=False)
                    
                # Right Chat Interface
                with gr.Column(scale=3):
                    gr.Markdown("### 🛠️ Agent Execution Steps")
                    agent_steps = gr.Markdown("⏳ Waiting for request...", elem_id="agent-steps")
                    chatbot = gr.Chatbot(label="Chat History", height=500)
                    with gr.Row():
                        msg = gr.Textbox(label="Your Request", placeholder="E.g., Analyze my sheets and email a report...", scale=8)
                        submit_btn = gr.Button("Send 🚀", variant="primary", scale=1)
                    clear = gr.ClearButton([msg, chatbot], value="Clear History 🗑️")

            submit_btn.click(respond, inputs=[msg, chatbot, expense_file, expense_url, revenue_file, revenue_url, budget_marketing, budget_operations, budget_travel], outputs=[msg, chatbot, pdf_download, agent_steps]).then(update_overview, inputs=[month_slider], outputs=[val_spend, val_anom, val_burn, plot_trend, val_time, month_selector])
            msg.submit(respond, inputs=[msg, chatbot, expense_file, expense_url, revenue_file, revenue_url, budget_marketing, budget_operations, budget_travel], outputs=[msg, chatbot, pdf_download, agent_steps]).then(update_overview, inputs=[month_slider], outputs=[val_spend, val_anom, val_burn, plot_trend, val_time, month_selector])

        # --- TAB 2: Dashboard ---
        with gr.Tab("📊 Dashboard") as dashboard_tab:
            with gr.Row():
                with gr.Column(scale=1, elem_classes=["sidebar-panel"]):
                    gr.Markdown("### 📅 History Explorer")
                    month_slider.render()
                    refresh_dashboard_btn = gr.Button("🔄 Sync Data", variant="secondary")
                    month_selector.render()
                with gr.Column(scale=3):
                    gr.Markdown("### 📈 Executive Overview")
                    with gr.Row():
                        with gr.Column(elem_classes=["metric-card"]): val_spend.render()
                        with gr.Column(elem_classes=["metric-card"]): val_anom.render()
                        with gr.Column(elem_classes=["metric-card"]): val_burn.render()
                    plot_trend.render()
                    gr.Markdown("### 🗓️ Monthly Deep Dive")
                    with gr.Row():
                        with gr.Column():
                            m_val_spend = gr.Textbox(label="Month Spend", interactive=False)
                            m_val_rev = gr.Textbox(label="Month Revenue", interactive=False)
                            m_val_profit = gr.Textbox(label="Month Profit/Loss", interactive=False)
                        with gr.Column(scale=2): m_plot = gr.Plot(label="Monthly Category Breakdown")
                    val_time.render()
            
            refresh_dashboard_btn.click(update_overview, inputs=[month_slider], outputs=[val_spend, val_anom, val_burn, plot_trend, val_time, month_selector])
            month_slider.change(update_overview, inputs=[month_slider], outputs=[val_spend, val_anom, val_burn, plot_trend, val_time, month_selector])
            month_selector.change(update_monthly_view, inputs=[month_selector], outputs=[m_val_spend, m_val_rev, m_val_profit, m_plot])
            dashboard_tab.select(update_overview, inputs=[month_slider], outputs=[val_spend, val_anom, val_burn, plot_trend, val_time, month_selector])

        # --- TAB 3: Google Auth ---
        with gr.Tab("🔑 Google Auth") as auth_tab:
            gr.Markdown("### 🔓 Google Services Authentication")
            gr.Markdown("Authorize the agent to access Gmail, Calendar, and Sheets.")
            
            auth_status = gr.Markdown("Checking authentication status...")
            
            with gr.Row() as login_row:
                get_link_btn = gr.Button("Get Login Link 🔗", variant="primary")
                refresh_status_btn = gr.Button("🔄 Refresh Status", variant="secondary")
            
            link_display = gr.Markdown("", visible=False)
            
            with gr.Accordion("⚠️ Manual Authentication Fallback", open=False) as fallback_accordion:
                gr.Markdown("If the automatic redirect doesn't work (e.g., firewall restriction), copy the `code=...` value from the redirected page's URL address bar and paste it below.")
                auth_code_input = gr.Textbox(label="Paste Authorization Code", placeholder="E.g., 4/0AdkVLPy...")
                submit_code_btn = gr.Button("Complete Manual Authentication ✅", variant="secondary")
                result_msg = gr.Markdown("")
            
            # Event bindings
            auth_tab.select(check_auth_status, outputs=[auth_status, login_row, link_display])
            refresh_status_btn.click(check_auth_status, outputs=[auth_status, login_row, link_display])
            
            # Clicking get link button shows login link markdown
            get_link_btn.click(get_auth_link, outputs=[link_display, link_display])
            
            # Manual code submit
            submit_code_btn.click(submit_auth_code, inputs=[auth_code_input], outputs=[result_msg]).then(
                check_auth_status, outputs=[auth_status, login_row, link_display]
            )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False, theme=theme, css=css)
