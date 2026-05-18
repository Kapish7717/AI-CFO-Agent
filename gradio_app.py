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
.gradio-container {
    font-family: 'Inter', system-ui, -apple-system, sans-serif !important;
}
h1 {
    color: #1E3A8A;
    font-weight: 800;
    margin-bottom: 0.5rem;
}
p.subtitle {
    color: #4B5563;
    font-size: 1.1rem;
    margin-bottom: 2rem;
    font-weight: 500;
}
.sidebar-panel {
    background-color: #F3F4F6;
    padding: 1.5rem;
    border-radius: 12px;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
}
.metric-card {
    background: white;
    padding: 1.5rem;
    border-radius: 10px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    text-align: center;
    border-top: 4px solid #3b82f6;
}
.metric-value {
    font-size: 2rem;
    font-weight: 700;
    color: #1e293b;
}
.metric-title {
    font-size: 0.9rem;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-top: 0.5rem;
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

def get_auth_link():
    try:
        response = httpx.get("http://localhost:8000/auth/url")
        url = response.json().get("url")
        return f"### 🔗 [Click here to Login with Google]({url})\n\n1. Click the link above (opens in a new tab).\n2. Authorize the application.\n3. Copy the code from the address bar.\n4. Paste it below.", gr.update(visible=True)
    except Exception as e:
        return f"❌ Error: {e}", gr.update(visible=False)

def submit_auth_code(code):
    try:
        response = httpx.post("http://localhost:8000/auth/exchange", json={"code": code})
        return response.json().get("message")
    except Exception as e:
        return f"❌ Error: {e}"

with gr.Blocks(title="AI CFO Agent") as demo:
    gr.HTML("<h1 style='text-align: center;'>💼 Autonomous AI CFO</h1>")
    gr.HTML("<p class='subtitle' style='text-align: center;'>Your personal executive financial agent. Analyze data, detect anomalies, and report findings.</p>")
    
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
        with gr.Tab("🔑 Google Auth"):
            gr.Markdown("### 🔓 Google Services Authentication")
            gr.Markdown("If you haven't uploaded `token.json`, use this tab to authorize the agent to access Gmail, Calendar, and Sheets.")
            
            with gr.Row():
                get_link_btn = gr.Button("1. Get Login Link 🔗", variant="primary")
                auth_status = gr.Markdown("Click the button to start.")
            
            with gr.Column(visible=False) as auth_input_col:
                auth_code_input = gr.Textbox(label="2. Paste Authorization Code", placeholder="Paste the code from your browser here...")
                submit_code_btn = gr.Button("3. Complete Authentication ✅", variant="secondary")
                result_msg = gr.Markdown("")
            
            get_link_btn.click(get_auth_link, outputs=[auth_status, auth_input_col])
            submit_code_btn.click(submit_auth_code, inputs=[auth_code_input], outputs=[result_msg])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False, theme=theme, css=css)
