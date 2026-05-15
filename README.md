# AI CFO Agent 🤖💼

An autonomous, agentic AI workflow built with **LangGraph** and **Llama-3** (running locally via **Ollama**) that acts as a Chief Financial Officer. This agent automatically ingests financial data, detects anomalies, generates professional executive PDF reports, and communicates with stakeholders via email and calendar invites.

## ✨ Features

- **Multi-Source Data Ingestion**: Seamlessly reads expense and revenue data from Google Sheets, CSV, or Excel files.
- **Intelligent Anomaly Detection**: Uses Pandas to analyze Month-over-Month (MoM) variances, flag duplicate transactions, and identify unusual spending spikes.
- **Automated PDF Reporting**: Generates a professional, formatted executive summary report detailing financial health and highlighted anomalies.
- **Agentic Orchestration (LangGraph)**: Uses a ReAct architecture to intelligently decide when to use tools, process data, and route tasks.
- **Local Data Security**: Uses **Ollama** to process all financial data locally, ensuring no sensitive data leaves your infrastructure.
- **Automated Communication**: 
  - 📧 **Gmail API Integration**: Automatically attaches the generated PDF report and emails it to stakeholders.
  - 📅 **Google Calendar Integration**: Autonomously schedules budget review meetings based on natural language prompts.

## 🛠️ Tech Stack

- **Core Frameworks**: [LangGraph](https://python.langchain.com/v0.1/docs/langgraph/), [LangChain](https://python.langchain.com/)
- **LLM**: Llama-3 (Local via [Ollama](https://ollama.com/))
- **Data Processing**: Pandas
- **External Integrations**: Gmail API, Google Calendar API
- **Reporting**: PDF generation tools (ReportLab)

## 🚀 How it Works

The agent follows a stateful execution graph:
1. **Ingest**: The user provides a natural language prompt with links to financial datasets.
2. **Analyze**: The agent triggers the `detect_financial_anomalies` tool to evaluate the data.
3. **Report**: The agent calls `generate_cfo_pdf_report` to create a local PDF.
4. **Communicate**: The agent routes the PDF through the `send_email` tool and schedules follow-ups via the `schedule_meeting` tool.
5. **Terminate**: The process finishes securely once all tasks in the prompt are completed.

## 📦 Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/ai-cfo-agent.git
   cd ai-cfo-agent
   ```

2. **Install Ollama:**
   Download and install Ollama from [ollama.com](https://ollama.com). Then pull the Llama 3.1 model:
   ```bash
   ollama pull llama3.1
   ```

3. **Create a virtual environment and install dependencies:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   pip install -r requirements.txt
   ```

4. **Set up your Environment Variables (Optional):**
   Create a `.env` file in the root directory to specify the model if different from the default:
   ```env
   OLLAMA_MODEL=llama3.1
   ```

5. **Set up Google Credentials:**
   - Go to the [Google Cloud Console](https://console.cloud.google.com/).
   - Enable the **Gmail API** and **Google Calendar API**.
   - Download your OAuth 2.0 Client credentials and save the file as `credentials.json` in the root directory.

6. **Run the Agent:**
   ```bash
   python agent.py
   ```
   *(On the first run, a browser window will open asking you to authenticate with your Google account).*

## 📈 Future Enhancements
- Add interactive data visualization via Streamlit/Gradio.
- Support for real-time bank API integrations (e.g., Plaid).
- More complex financial forecasting models.

---
*Built with ❤️ using LangGraph and Python.*
