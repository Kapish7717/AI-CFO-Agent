// Typed browser-side client for the FastAPI AI CFO backend.
// Auth model matches the backend as written: login returns a user object (no JWT).
// We persist the user in localStorage and forward user_id as a query param.
//
// VITE_API_BASE_URL overrides the target (used in dev, e.g. http://127.0.0.1:8000).
// When unset, requests go to the same origin that served the page — so the
// production build served by FastAPI (port 7860) talks to itself automatically.

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export interface StoredUser {
  id: number;
  email: string;
  full_name: string;
  role: string;
  avatar_url?: string | null;
}

const USER_KEY = "aicfo.user";

export function getStoredUser(): StoredUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as StoredUser) : null;
  } catch {
    return null;
  }
}

export function setStoredUser(user: StoredUser | null) {
  if (typeof window === "undefined") return;
  if (!user) window.localStorage.removeItem(USER_KEY);
  else window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  window.dispatchEvent(new CustomEvent("aicfo:user-changed"));
}

export function currentUserId(): number {
  return getStoredUser()?.id ?? 1;
}

function withUserId(path: string, userId?: number): string {
  const uid = userId ?? currentUserId();
  const sep = path.includes("?") ? "&" : "?";
  return `${API_BASE_URL}${path}${sep}user_id=${encodeURIComponent(uid)}`;
}

function url(path: string): string {
  return `${API_BASE_URL}${path}`;
}

async function handle<T>(res: Response): Promise<T> {
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  if (!res.ok) {
    const msg =
      (body && (body.detail || body.error || body.message)) ||
      res.statusText ||
      "Request failed";
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return body as T;
}

function safeJson(text: string): any {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

// ---------- Auth ----------
export const AuthAPI = {
  register: (payload: { email: string; password: string; full_name: string; role?: string }) =>
    fetch(url("/api/auth/register"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) => handle<{ success: boolean; user_id: number }>(r)),

  login: (payload: { email: string; password: string }) =>
    fetch(url("/api/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then((r) => handle<{ success: boolean; user: StoredUser }>(r)),

  me: (userId?: number) => fetch(withUserId("/api/auth/me", userId)).then((r) => handle<StoredUser>(r)),

  googleAuthUrl: (userId?: number) =>
    fetch(withUserId("/auth/url", userId)).then((r) => handle<{ url: string }>(r)),

  googleStatus: (userId?: number) =>
    fetch(withUserId("/auth/status", userId)).then((r) => handle<{ authenticated: boolean }>(r)),

  googleDisconnect: (userId?: number) =>
    fetch(withUserId("/api/auth/google/disconnect", userId), { method: "POST" }).then((r) =>
      handle<{ success: boolean }>(r),
    ),
};

// ---------- Settings ----------
export interface UserSettings {
  budget_marketing: number;
  budget_operations: number;
  budget_travel: number;
  expense_file_path: string | null;
  expense_file_name: string | null;
  expense_url: string | null;
  revenue_file_path: string | null;
  revenue_file_name: string | null;
  revenue_url: string | null;
  selected_month: string | null;
  llm_primary_provider: string | null;
  llm_primary_model: string | null;
  llm_fallback_provider: string | null;
  llm_fallback_model: string | null;
  api_key: string | null;
  fallback_api_key: string | null;
  report_email: string | null;
  report_schedule: string | null;
}

export const SettingsAPI = {
  get: (userId?: number) => fetch(withUserId("/api/user-settings", userId)).then((r) => handle<UserSettings>(r)),
  update: (updates: Partial<UserSettings>, userId?: number) =>
    fetch(withUserId("/api/user-settings", userId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    }).then((r) => handle<{ success: boolean }>(r)),
};

export interface ProviderList {
  providers: string[];
}

export interface ModelList {
  models: string[];
}

export const ProvidersAPI = {
  list: () => fetch(url("/api/providers")).then((r) => handle<ProviderList>(r)),
  models: (provider: string, apiKey?: string) => {
    const q = new URLSearchParams({ provider });
    if (apiKey) q.set("api_key", apiKey);
    return fetch(url(`/api/models?${q.toString()}`)).then((r) => handle<ModelList>(r));
  },
};

// ---------- Dashboard ----------
export interface DashboardTrend {
  text: string;
  color: "green" | "red";
  is_positive: boolean;
}
export interface DashboardCategory {
  category: string;
  amount: number;
  amount_formatted: string;
  percent: number;
}
export interface DashboardPoint {
  date: string;
  revenue: number;
  expenses: number;
  net_profit: number;
}
export interface DashboardOverview {
  total_revenue: string;
  total_expenses: string;
  net_profit: string;
  cash_balance: string;
  revenue_trend: DashboardTrend;
  expense_trend: DashboardTrend;
  profit_trend: DashboardTrend;
  cash_trend: DashboardTrend;
  profit_margin: number;
  profit_margin_trend: DashboardTrend;
  categories: DashboardCategory[];
  cash_inflow: string;
  cash_outflow: string;
  net_cash_flow: string;
  recent_insights: string[];
  trend_data: DashboardPoint[];
  available_months: string[];
  selected_month: string;
  date_range_label: string;
  last_sync: string;
  budget_marketing: number;
  budget_operations: number;
  budget_travel: number;
  error?: string;
}

export const DashboardAPI = {
  overview: (month?: string, userId?: number) => {
    const q = month ? `/api/dashboard/overview?month=${encodeURIComponent(month)}` : "/api/dashboard/overview";
    return fetch(withUserId(q, userId)).then((r) => handle<DashboardOverview>(r));
  },
  downloadReportUrl: (userId?: number) => withUserId("/api/download-report", userId),
};

// ---------- Chat ----------
export interface ChatMessage {
  sender: "user" | "agent";
  text: string;
  timestamp?: string;
}

export const ChatAPI = {
  history: (userId?: number) => fetch(withUserId("/api/chat/history", userId)).then((r) => handle<ChatMessage[]>(r)),
};

// ---------- Uploads ----------
export const UploadAPI = {
  file: async (file: File, fileType: "expense" | "revenue", userId?: number) => {
    const uid = userId ?? currentUserId();
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(
      `${API_BASE_URL}/api/upload?user_id=${encodeURIComponent(uid)}&file_type=${fileType}`,
      { method: "POST", body: form },
    );
    return handle<{ file_path?: string; filename?: string; error?: string }>(res);
  },
};

// ---------- Stripe ----------
export interface StripeStatus {
  connected: boolean;
  status?: string | null;
  last_synced_at?: string | null;
  record_count?: number | null;
  error_message?: string | null;
}

export interface StripeConnectResult {
  connected: boolean;
  source: string;
  synced: number;
  total: number;
  error?: string;
}

export const StripeAPI = {
  connect: (apiKey: string, userId?: number) =>
    fetch(withUserId("/api/integrations/stripe/connect", userId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey }),
    }).then((r) => handle<StripeConnectResult>(r)),

  status: (userId?: number) =>
    fetch(withUserId("/api/integrations/stripe/status", userId)).then((r) => handle<StripeStatus>(r)),

  disconnect: (userId?: number) =>
    fetch(withUserId("/api/integrations/stripe/disconnect", userId), {
      method: "POST",
    }).then((r) => handle<{ success: boolean; connected: boolean }>(r)),
};

// ---------- AI Agent ----------
export interface AgentRunStep {
  step: string;
  message: string;
}

export interface AgentRunResult {
  success: boolean;
  steps: AgentRunStep[];
  message: string;
  email?: string | null;
}

export interface DataQueryResult {
  answer: string;
  success: boolean;
}

export const AgentAPI = {
  run: (toEmail?: string | null, userId?: number) =>
    fetch(withUserId("/api/agent/run", userId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId ?? currentUserId(), to_email: toEmail || null }),
    }).then((r) => handle<AgentRunResult>(r)),

  dataQuery: (question: string, userId?: number) =>
    fetch(withUserId("/api/chat/data-query", userId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId ?? currentUserId(), question }),
    }).then((r) => handle<DataQueryResult>(r)),
};
