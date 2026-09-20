# 🤖 AI CFO Agent

**Your Autonomous Financial Command Center**

Ingest data from multiple sources, detect anomalies and budget breaches, query your transaction database in natural language, generate professional PDF reports, dispatch them by email, and schedule review meetings — all orchestrated by an LLM agent.

🔗 **[Check it live here](https://ai-cfo-agent-tau.vercel.app)**

[![Live Frontend on Vercel](https://img.shields.io/badge/Live%20App-Vercel-black?style=for-the-badge&logo=vercel)](https://ai-cfo-agent-tau.vercel.app/)
[![Backend on Render](https://img.shields.io/badge/API-Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)](https://YOUR-RENDER-URL.onrender.com)
[![CI](https://github.com/Kapish7717/AI-CFO-Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Kapish7717/AI-CFO-Agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg?style=flat-square)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent-1c3d5a?style=flat-square)](https://langchain-ai.github.io/langgraph/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)

---

## 📚 Table of Contents

- [Overview](#-overview)
- [Features](#-features)
- [Architecture](#%EF%B8%8F-architecture)
- [Quick Start](#-quick-start-local-development)
- [Docker Deployment](#-docker-deployment)
- [Testing & Linting](#-testing--linting)
- [API Overview](#-api-overview)
- [Tech Stack](#-tech-stack)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🔎 Overview

The **AI CFO Agent** is an end-to-end autonomous financial analysis application built on a modular **FastAPI + LangGraph + MCP** architecture. A FastMCP server exposes core financial tools to a LangGraph ReAct agent, while a TanStack Start (React 19) dashboard provides charts, conversational analytics, and configuration.

Think of it as a financial analyst that never sleeps: it ingests your transactions, watches for anomalies and budget breaches, answers questions about your numbers in plain English, and proactively reports and escalates when something needs your attention.

---

## ✨ Features

| | |
|---|---|
| 📊 **Multi-Source Data Ingestion** | Load transactions from CSVs, Excel files, bank-statement PDFs (pdfplumber), or Google Sheets — with fuzzy column mapping and merge-upsert deduplication. |
| 💳 **Stripe Integration** | Connect a Stripe account to pull charges into a canonical `unified_transactions` store; background sync runs continuously and a signature-verified webhook endpoint keeps data fresh. |
| 🗄️ **PostgreSQL Storage (Supabase)** | All users, settings, transactions, chat history, and OAuth tokens live in Postgres; PDFs and breach reports upload to Supabase Storage (`cfo-agent-files` bucket). |
| 🚨 **Anomaly & Budget Breach Detection** | Z-score, IQR, month-over-month, and rule-based detectors plus category-wise budget caps, with severity flags persisted per transaction. |
| 💬 **Conversational Analytics (RAG)** | Ask questions in natural language — a Text-to-SQL pipeline with Jina reranking answers from your actual transaction tables, guarded to read-only queries. |
| 📈 **Forecasting** | Revenue/expense trend projections surfaced on a dedicated Forecasts page. |
| 📄 **Automated PDF Reporting** | ReportLab + Matplotlib reports with LLM-written narratives, limited to the trailing 12 months. |
| 📧 **Automated Email Dispatch** | Google OAuth (per-user tokens stored in the DB) sends PDF reports via Gmail with breach-warning summaries. |
| 📅 **Meeting Orchestration** | Schedules "Financial Budget Review" meetings on Google Calendar when critical anomalies occur. |
| ⏰ **Scheduled Reports** | Configure a daily HH:MM report time per user; a background loop generates and emails reports automatically. |
| 🔐 **Multi-User & Secure** | JWT authentication (PBKDF2-hashed passwords), per-user data isolation, pluggable LLM providers (Groq, OpenAI, Gemini, Anthropic) per session. |

---

## 🏗️ Architecture

```
┌──────────────────────┐      ┌───────────────────────────────────┐
│  Frontend (SPA)      │ HTTP │  FastAPI Backend (app/main.py)    │
│  TanStack Start      │◄────►│  ├─ 10 API routers (app/api/)     │
│  React 19 + Vite 8   │ JWT  │  ├─ Deterministic agent runner    │
│  Tailwind 4          │      │  └─ Background loops (reports,    │
└──────────────────────┘      │     Stripe sync)                  │
                               └────────┬───────────────────────────┘
                                        │ stdio (langchain-mcp-adapters)
                               ┌────────▼───────────────────────────┐
                               │  LangGraph Agent (ReAct-style)     │
                               │  app/agents/cfo_agent.py           │
                               │  agent → tools → halt nodes        │
                               └────────┬───────────────────────────┘
                                        │ FastMCP
                               ┌────────▼───────────────────────────┐
                               │  MCP Server: CFO_Central_Server    │
                               │  app/agents/mcp_server.py          │
                               │  ① authenticate_google             │
                               │  ② ingest_financial_data           │
                               │  ③ detect_financial_anomalies      │
                               │  ④ generate_cfo_pdf_report          │
                               │  ⑤ send_email_report                │
                               │  ⑥ schedule_meeting                 │
                               └───────────────────────────────────┘
```

**Project layout:**

```
├── app/
│   ├── main.py            # FastAPI entry point (serves API + built SPA)
│   ├── agents/             # LangGraph graph + FastMCP tool server
│   ├── api/                # Route routers: auth, dashboard, chat, forecast,
│   │                       # anomaly, report, integrations, providers, settings, agent
│   ├── core/                # Settings (pydantic), logging, security (JWT/PBKDF2)
│   ├── db/                  # psycopg2 pool, schema init/migrations, Supabase storage
│   ├── services/             # Agent runner, RAG (Text-to-SQL), LLM factory,
│   │                         # Stripe sync, budget breaches, sessions
│   └── tools/                # Data ingestion, anomaly detection, PDF report generator
├── frontend/               # TanStack Start SPA (routes/, components/, lib/)
├── scripts/                # Model discovery CLI
├── tests/                  # pytest suite + eval harnesses + fixtures
├── Dockerfile              # Multi-stage build (node:20 → python:3.12-slim)
├── docker-compose.yml      # api + postgres:16 stack
└── start.sh                # Production launcher (uvicorn on :7860)
```

---

## 🚀 Quick Start (Local Development)

### Prerequisites
- Python 3.10+ (CI uses 3.11, Docker ships 3.12)
- Node.js 20+ & npm
- A PostgreSQL database (Supabase recommended, or use the bundled `docker-compose` Postgres)
- Google Cloud project with OAuth credentials for Gmail / Calendar / Sheets

### Configuration (`.env`)
Copy the template and fill in real values:
```bash
cp .env.example .env
```
```env
APP_ENV=development

# Database (required in every environment)
DATABASE_URL=postgresql://postgres.xxx:password@aws-0-xx.pooler.supabase.com:6543/postgres

# Auth — required in production (APP_ENV=production)
JWT_SECRET_KEY=

# LLM providers
GROQ_API_KEY=
GROQ_MODEL=llama-3.1-8b-instant
JINA_API_KEY=          # enables reranked Text-to-SQL chat

# Supabase object storage (reports/uploads/breaches)
SUPABASE_URL=
SUPABASE_KEY=

# Optional integrations
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
GOOGLE_CREDENTIALS_JSON=
```
See [.env.example](.env.example) for every variable, including CORS, upload limits, and demo-user seeding.

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Kapish7717/AI-CFO-Agent.git
   cd AI-CFO-Agent
   ```

2. **Backend:**
   ```bash
   python -m venv venv
   source venv/bin/activate        # On Windows: .\venv\Scripts\activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```

3. **Frontend (dev server with hot reload):**
   ```bash
   cd frontend
   npm install
   npm run dev                     # http://localhost:5173, expects API on :8000
   ```

> In production mode the backend serves the built frontend itself, so a single process on one port is enough (see below).

---

## 🐳 Deployment

### Local stack (API + Postgres)
```bash
docker compose up --build
```
- App: **http://localhost:7860**
- Postgres 16 on `localhost:5432` (db `cfo_agent`, user `cfo`, password from `POSTGRES_PASSWORD`)

### Production: Vercel (frontend) + Render (backend)
- **Frontend** — the `frontend/` TanStack Start app is deployed on **Vercel**: [YOUR-VERCEL-URL.vercel.app](https://YOUR-VERCEL-URL.vercel.app). Set `VITE_API_URL` (or equivalent) to the Render API URL as a Vercel environment variable.
- **Backend** — the FastAPI service is deployed on **Render**: [YOUR-RENDER-URL.onrender.com](https://YOUR-RENDER-URL.onrender.com). Configure the environment variables from `.env.example` (`DATABASE_URL`, `JWT_SECRET_KEY`, LLM provider keys, Supabase keys, etc.) in the Render dashboard. Render builds from the repo's `Dockerfile` / `requirements.txt`.
- Push to `main` to trigger redeploys on both platforms.

### Single-container Docker (self-host / other platforms)
The multi-stage `Dockerfile` builds the React frontend with Node 20, then serves it from the Python image via `start.sh` — useful if you want to self-host both frontend and backend from one container instead of the Vercel/Render split above.

```bash
docker build -t ai-cfo-agent .
docker run -p 7860:7860 \
  -e DATABASE_URL="postgresql://..." \
  -e JWT_SECRET_KEY="..." \
  ai-cfo-agent
```

---

## 🧪 Testing & Linting

```bash
pip install -r requirements-dev.txt

pytest tests -q                       # full offline test suite
coverage run -m pytest tests -q       # with coverage (CI enforces gates)

ruff check app tests scripts          # Python linting
cd frontend && npm run lint           # ESLint + Prettier
```

The suite covers the agent graph (mocked MCP tools), the deterministic pipeline, anomaly detection golden files, ingestion, the RAG pipeline, security primitives, and trajectory/report-content eval harnesses (`tests/evals/`).

---

## 🔌 API Overview

| Area | Endpoints |
|---|---|
| Health | `GET /health`, `GET /healthz` |
| Auth | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me` |
| Google OAuth | `GET /auth/url`, `POST /auth/exchange`, `GET /auth/callback`, `GET /auth/status` |
| Dashboard | `GET /api/dashboard/overview` |
| Agent | `POST /api/agent/run` (deterministic ingest → detect → report → email pipeline) |
| Chat / RAG | `GET /api/chat/history`, `POST /api/chat/data-query` |
| Forecast | `POST /api/v1/forecast` |
| Anomaly | `POST /api/v1/anomaly` |
| Data | `POST /api/upload`, `POST /api/v1/data/connect` |
| Stripe | `POST /api/integrations/stripe/connect`, `GET .../status`, `POST .../disconnect`, `POST /webhooks/stripe` |
| Models | `GET /api/providers`, `GET /api/models?provider=` |
| Reports | `POST /api/v1/report`, `GET /api/download-report` |
| Settings | `GET /api/user-settings`, `POST /api/user-settings` |

---

## 🧰 Tech Stack

**Backend:** FastAPI · LangGraph · FastMCP · psycopg2 · pdfplumber · ReportLab · Matplotlib
**Frontend:** TanStack Start · React 19 · Vite 8 · Tailwind CSS 4
**Data & Infra:** PostgreSQL (Supabase) · Supabase Storage · Docker · GitHub Actions CI
**LLM Providers:** Groq · OpenAI · Gemini · Anthropic (pluggable per session)
**Integrations:** Stripe · Google OAuth (Gmail, Calendar, Sheets) · Jina Reranker

---

## 🗺️ Roadmap

- [ ] Multi-currency support
- [ ] Role-based access control for team accounts
- [ ] Slack/Teams alerting channel alongside email
- [ ] Expanded forecasting models (seasonal decomposition)

---

## 🤝 Contributing

Issues and PRs are welcome. Please run the test suite and linters (see [Testing & Linting](#-testing--linting)) before opening a pull request.

---

## 📝 License

This project is licensed under the MIT License.
