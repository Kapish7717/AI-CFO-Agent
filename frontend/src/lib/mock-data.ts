export const kpis = [
  { label: "Revenue (MTD)", value: "$1,284,930", delta: "+12.4%", trend: "up" as const, sub: "vs prior month" },
  { label: "Operating Expenses", value: "$742,180", delta: "-3.1%", trend: "down" as const, sub: "vs prior month" },
  { label: "Net Cash Flow", value: "$412,750", delta: "+18.9%", trend: "up" as const, sub: "30-day rolling" },
  { label: "Cash Runway", value: "17.4 mo", delta: "+1.2 mo", trend: "up" as const, sub: "at current burn" },
];

export const revenueSeries = [
  { month: "Jan", revenue: 820, expenses: 640 },
  { month: "Feb", revenue: 890, expenses: 670 },
  { month: "Mar", revenue: 940, expenses: 690 },
  { month: "Apr", revenue: 1010, expenses: 720 },
  { month: "May", revenue: 1080, expenses: 705 },
  { month: "Jun", revenue: 1140, expenses: 740 },
  { month: "Jul", revenue: 1210, expenses: 725 },
  { month: "Aug", revenue: 1284, expenses: 742 },
];

export const forecastSeries = [
  ...revenueSeries.map((d) => ({ ...d, forecast: null as number | null })),
  { month: "Sep", revenue: null as number | null, expenses: 760, forecast: 1330 },
  { month: "Oct", revenue: null, expenses: 775, forecast: 1395 },
  { month: "Nov", revenue: null, expenses: 790, forecast: 1460 },
  { month: "Dec", revenue: null, expenses: 810, forecast: 1540 },
];

export const expenseBreakdown = [
  { name: "Payroll", value: 342 },
  { name: "Infrastructure", value: 128 },
  { name: "Marketing", value: 96 },
  { name: "Software", value: 84 },
  { name: "Operations", value: 62 },
  { name: "Other", value: 30 },
];

export const anomalies = [
  { id: "ANM-4821", severity: "high", vendor: "Skyline Freight Ltd", amount: "$48,920", reason: "Duplicate invoice detected within 48h window", date: "Aug 24" },
  { id: "ANM-4820", severity: "medium", vendor: "Northwind Cloud", amount: "$12,450", reason: "Spend 340% above 90-day baseline", date: "Aug 23" },
  { id: "ANM-4818", severity: "high", vendor: "Unknown Payee", amount: "$8,200", reason: "First-time vendor, off-hours transaction", date: "Aug 22" },
  { id: "ANM-4815", severity: "low", vendor: "Acme Supplies", amount: "$3,120", reason: "Invoice above department cap by 8%", date: "Aug 21" },
];

export const dataSources = [
  { name: "Production Postgres", type: "PostgreSQL", records: "1.2M", status: "healthy", synced: "2 min ago" },
  { name: "QuickBooks Online", type: "Accounting", records: "84K", status: "healthy", synced: "12 min ago" },
  { name: "Stripe Payments", type: "Payments", records: "312K", status: "healthy", synced: "just now" },
  { name: "Snowflake Warehouse", type: "Database", records: "9.4M", status: "syncing", synced: "in progress" },
  { name: "Bank Statements Q3", type: "PDF", records: "3 files", status: "healthy", synced: "1 hr ago" },
  { name: "Gmail Invoices", type: "Email", records: "1,204", status: "error", synced: "auth expired" },
];

export const reports = [
  { name: "Executive Summary — August 2026", format: "PDF", size: "2.4 MB", generated: "Today · 09:12" },
  { name: "Q3 Forecast & Scenario Analysis", format: "PDF", size: "5.1 MB", generated: "Yesterday · 17:44" },
  { name: "Vendor Spend Deep Dive", format: "XLSX", size: "812 KB", generated: "Aug 25" },
  { name: "Cash Flow Weekly Digest", format: "PDF", size: "1.1 MB", generated: "Aug 22" },
  { name: "Budget Variance Report", format: "CSV", size: "94 KB", generated: "Aug 20" },
];

export const integrations = [
  { name: "PostgreSQL", category: "Database", connected: true },
  { name: "MySQL", category: "Database", connected: false },
  { name: "Snowflake", category: "Warehouse", connected: true },
  { name: "BigQuery", category: "Warehouse", connected: false },
  { name: "QuickBooks", category: "Accounting", connected: true },
  { name: "Xero", category: "Accounting", connected: false },
  { name: "Zoho Books", category: "Accounting", connected: false },
  { name: "SAP", category: "ERP", connected: false },
  { name: "Oracle ERP", category: "ERP", connected: false },
  { name: "Stripe", category: "Payments", connected: true },
  { name: "Razorpay", category: "Payments", connected: false },
  { name: "PayPal", category: "Payments", connected: false },
  { name: "Google Drive", category: "Storage", connected: true },
  { name: "Dropbox", category: "Storage", connected: false },
  { name: "OneDrive", category: "Storage", connected: false },
  { name: "Gmail", category: "Productivity", connected: false },
  { name: "Slack", category: "Productivity", connected: true },
  { name: "Microsoft Teams", category: "Productivity", connected: false },
];

export const providers = [
  { id: "openai", name: "OpenAI", models: ["gpt-4o", "gpt-4o-mini", "o1", "o1-mini"] },
  { id: "anthropic", name: "Anthropic", models: ["claude-sonnet-4.5", "claude-opus-4", "claude-haiku-4"] },
  { id: "google", name: "Google Gemini", models: ["gemini-2.5-pro", "gemini-2.5-flash"] },
  { id: "groq", name: "Groq", models: ["llama-3.3-70b", "mixtral-8x7b"] },
  { id: "openrouter", name: "OpenRouter", models: ["auto", "meta-llama/llama-3.1-405b"] },
  { id: "ollama", name: "Ollama (Local)", models: ["llama3.1", "qwen2.5", "mistral"] },
];
