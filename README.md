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

> Your Autonomous Financial Command Center. Ingest data, detect anomalies, query relational transactions databases, generate professional PDF reports, and schedule meetings seamlessly.

The **AI CFO Agent** is an end-to-end autonomous financial analysis application built with modern AI architectures. It leverages the **Model Context Protocol (MCP)** to equip a Large Language Model with dynamic tools for data processing, budget monitoring, relational database logging, and automated email reporting.

---

## ✨ Features

- **📊 Multi-Source Data Ingestion:** Effortlessly load financial records from CSVs, Excel files, or Google Sheets.
- **🗄️ Relational Database Storage:** Automatically stores and updates all parsed transaction records inside a **PostgreSQL database (Supabase)**.
- **🚨 Anomaly & Budget Breach Detection:** Automatically flags unexpected expenses and tracks category-wise budget caps.
- **📄 Automated PDF Reporting:** Generates comprehensive financial reports with charts, uploading PDF artifacts directly to **Supabase Storage**.
- **📧 Automated Email Dispatch:** Connects with your Google Account via secure OAuth to email PDF reports directly to stakeholders.
- **📅 Meeting Orchestration:** Automatically schedules follow-up meetings via Google Calendar when critical anomalies occur.
- **💬 Interactive React Dashboard:** A beautiful React-based conversational UI that displays dynamic charts, monthly overviews, and streams the agent's thought process live.

---

## 🏗️ Architecture

The system is modularized using the **Model Context Protocol (MCP)**:
- **Client (Frontend):** A React dashboard interface (`frontend/`) for charts, transaction visualizers, and budget configuration.
- **API Backend:** A FastAPI application (`api.py`) that handles asynchronous streaming of the agent's thoughts to the frontend and manages the Google OAuth flow.
- **Agent Orchestrator:** LangGraph orchestrates the sequential execution (Ingestion ➡️ Analysis ➡️ Reporting).
- **FastMCP Server:** Exposes core Python financial scripts as standardized tools to the AI agent (`mcp_client.py`).

---

## 🚀 Quick Start (Local)

### Prerequisites
- Python 3.10+
- Node.js & npm (for React frontend)
- Google Cloud Project with OAuth credentials (for Gmail/Calendar APIs)
- Supabase Project (PostgreSQL and Cloud Storage bucket `cfo-agent-files`)

### Configuration (`.env`)
Create a `.env` file in the root directory:
```env
GROQ_API_KEY=your_groq_api_key
GOOGLE_API_KEY=your_google_search_api_key

# Supabase Credentials
DATABASE_URL=postgresql://postgres.xxx:password@aws-0-xx.pooler.supabase.com:6543/postgres
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your_supabase_anon_or_service_role_key
```

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Kapish7717/AI-CFO-Agent.git
   cd AI-CFO-Agent
   ```

2. **Backend Setup:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn api:app --reload --port 7860
   ```

3. **Frontend Setup:**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

---

## 🐳 Docker Deployment

This project is fully containerized. The provided `Dockerfile` and `start.sh` run the backend FastAPI server and the built React frontend static files simultaneously.

```bash
docker build -t ai-cfo-agent .
docker run -p 7860:7860 ai-cfo-agent
```

## 📝 License
This project is licensed under the MIT License.
