---
title: AI CFO AGENT
emoji: 💰
colorFrom: blue
colorTo: green
sdk: docker
pinned: false
---

# 🤖 AI CFO Agent

[![Live Demo on Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Live%20Demo-Hugging%20Face%20Spaces-blue?style=for-the-badge)](https://huggingface.co/spaces/Kaps07/AI-CFO-AGENT)

> Your Autonomous Financial Command Center. Ingest data, detect anomalies, generate professional PDF reports, and schedule meetings seamlessly.

The **AI CFO Agent** is an end-to-end autonomous financial analysis application built with modern AI architectures. It leverages the **Model Context Protocol (MCP)** to equip a Large Language Model with dynamic tools for data processing, budget monitoring, and automated email reporting.

## ✨ Features

- **📊 Multi-Source Data Ingestion:** Effortlessly load financial records from CSVs, Excel files, or Google Sheets.
- **🚨 Anomaly & Budget Breach Detection:** Automatically flags unexpected expenses and tracks category-wise budget caps.
- **📄 Automated PDF Reporting:** Generates comprehensive, month-wise financial reports with automated appendix sections.
- **📧 Automated Email Dispatch:** Connects with your Google Account via secure OAuth to email reports directly to stakeholders.
- **📅 Meeting Orchestration:** Automatically schedules follow-up meetings via Google Calendar when critical anomalies occur.
- **💬 Interactive Dashboard:** A beautiful Gradio-based conversational UI that streams the agent's thought process and execution steps live.

## 🏗️ Architecture

The system is modularized using the **Model Context Protocol (MCP)**:
- **Client (Frontend):** A Gradio chat interface (`gradio_app.py`) for user interaction and budget configuration.
- **Agent Orchestrator:** LangGraph orchestrates the sequential execution (Ingestion ➡️ Analysis ➡️ Reporting).
- **FastMCP Server:** Exposes core Python financial scripts as standardized tools to the AI agent (`mcp_client.py`).

## 🚀 Quick Start (Local)

### Prerequisites
- Python 3.10+
- Google Cloud Project with OAuth credentials (for Gmail/Calendar APIs)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Kapish7717/AI-CFO-Agent.git
   cd AI-CFO-Agent
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Google Auth (MANDATORY FIRST STEP):**
   The agent requires access to Google Services (Gmail, Calendar, Sheets) to fully function. You **must** authenticate before giving the agent any financial tasks:
   - Place your Google Cloud `credentials.json` in the project's root directory (or securely add it as a secret on Hugging Face).
   - Once the app is running, go to the **"🔑 Google Auth"** tab in the UI.
   - Click "Get Login Link", authorize the app in your browser, and paste the provided code back into the UI to complete the setup.

4. **Run the Application:**
   ```bash
   python gradio_app.py
   ```

## 🐳 Docker / Hugging Face Deployment

This project is fully containerized and pre-configured for Hugging Face Spaces.
The provided `Dockerfile` and `start.sh` run the backend MCP server and the Gradio frontend simultaneously.

```bash
docker build -t ai-cfo-agent .
docker run -p 7860:7860 ai-cfo-agent
```

## 🤝 Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License
This project is licensed under the MIT License.
