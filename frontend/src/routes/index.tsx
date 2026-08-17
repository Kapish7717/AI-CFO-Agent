import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight, CheckCircle2, Clock, Download, Loader2, Mail, Play, Sparkles } from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader } from "@/components/page-header";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AgentAPI, DashboardAPI, SettingsAPI } from "@/lib/api";
import { GoogleAuthBar } from "@/components/google-auth-bar";
import { toast } from "sonner";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Dashboard — AI CFO" },
      { name: "description", content: "Real-time financial KPIs, cash flow, forecasts, and anomaly signals in one command center." },
      { property: "og:title", content: "Dashboard — AI CFO" },
      { property: "og:description", content: "Real-time financial KPIs and autonomous insights." },
    ],
  }),
  component: Dashboard,
});

function Dashboard() {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["dashboard", month],
    queryFn: () => DashboardAPI.overview(month),
    refetchOnWindowFocus: false,
  });

  const months = data?.available_months ?? [];
  const selected = data?.selected_month ?? month ?? "";

  return (
    <div>
      <PageHeader
        eyebrow="Command Center"
        title={data?.date_range_label ? `Financial pulse · ${data.date_range_label}` : "Financial pulse"}
        description="Autonomous agents monitor revenue, expenses, and risk across every connected source — updated continuously."
        actions={
          <>
            {months.length > 0 && (
              <Select value={selected} onValueChange={(v) => setMonth(v)}>
                <SelectTrigger className="h-9 w-[160px]"><SelectValue placeholder="Month" /></SelectTrigger>
                <SelectContent>
                  {months.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
            <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
              {isFetching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
              Refresh
            </Button>
            <Button asChild size="sm">
              <a href="/chat"><Sparkles className="h-4 w-4" /> Ask AI CFO</a>
            </Button>
          </>
        }
      />

      <div className="px-6 py-6 md:px-10 space-y-8">
        <GoogleAuthBar />

        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading dashboard…</div>
        )}
        {isError && (
          <div className="rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
            Failed to load dashboard: {(error as Error).message}
          </div>
        )}
        {data && data.error && (
          <div className="rounded-xl border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
            Backend error: {data.error}
          </div>
        )}

        {data && !data.error && (
          <>
            {/* KPIs */}
            <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
              <KPI label="Total revenue" value={data.total_revenue} trend={data.revenue_trend} />
              <KPI label="Total expenses" value={data.total_expenses} trend={data.expense_trend} invert />
              <KPI label="Net profit" value={data.net_profit} trend={data.profit_trend} />
              <KPI label="Cash balance" value={data.cash_balance} trend={data.cash_trend} />
            </div>

            {/* AI Agent panel */}
            <AgentRunPanel />

            {/* Revenue vs Expenses */}
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2 rounded-xl border border-border bg-card p-6">
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-display text-2xl">Revenue vs Expenses</h3>
                    <p className="text-xs text-muted-foreground">{selected} · daily cumulative</p>
                  </div>
                  <div className="flex gap-4 text-xs">
                    <Legend color="var(--color-accent)" label="Revenue" />
                    <Legend color="var(--color-muted-foreground)" label="Expenses" />
                  </div>
                </div>
                <div className="mt-6 h-72">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data.trend_data} margin={{ left: -20, right: 8, top: 8 }}>
                      <defs>
                        <linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.28} />
                          <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid stroke="var(--color-border)" vertical={false} />
                      <XAxis dataKey="date" stroke="var(--color-muted-foreground)" fontSize={11} tickLine={false} axisLine={false} />
                      <YAxis stroke="var(--color-muted-foreground)" fontSize={11} tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={tooltipStyle} />
                      <Area type="monotone" dataKey="revenue" stroke="var(--color-accent)" strokeWidth={2} fill="url(#rev)" />
                      <Line type="monotone" dataKey="expenses" stroke="var(--color-muted-foreground)" strokeWidth={1.5} strokeDasharray="4 4" dot={false} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>

              <div className="rounded-xl border border-border bg-card p-6">
                <h3 className="font-display text-2xl">Expense Mix</h3>
                <p className="text-xs text-muted-foreground">{selected} allocation</p>
                <div className="mt-6 h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.categories.slice(0, 6)} layout="vertical" margin={{ left: 8, right: 16 }}>
                      <XAxis type="number" hide />
                      <YAxis dataKey="category" type="category" stroke="var(--color-muted-foreground)" fontSize={11} tickLine={false} axisLine={false} width={90} />
                      <Tooltip contentStyle={tooltipStyle} formatter={(v: any) => `$${Number(v).toLocaleString()}`} />
                      <Bar dataKey="amount" radius={[0, 4, 4, 0]}>
                        {data.categories.slice(0, 6).map((_, i) => (
                          <Cell key={i} fill={i === 0 ? "var(--color-primary)" : "var(--color-muted-foreground)"} fillOpacity={i === 0 ? 1 : 0.35 + (0.5 - i * 0.07)} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            {/* Cash flow + insights */}
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="rounded-xl border border-border bg-card p-6 lg:col-span-2">
                <h3 className="font-display text-2xl">Cash Flow Summary</h3>
                <p className="text-xs text-muted-foreground">{selected} · profit margin {data.profit_margin}%</p>
                <div className="mt-6 grid grid-cols-3 gap-4">
                  <CashCard label="Inflow" value={data.cash_inflow} tone="text-success" />
                  <CashCard label="Outflow" value={data.cash_outflow} tone="text-destructive" />
                  <CashCard label="Net" value={data.net_cash_flow} tone="text-foreground" />
                </div>
                <p className="mt-6 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">Last sync</p>
                <p className="text-sm num">{data.last_sync}</p>
              </div>

              <div className="rounded-xl border border-border bg-card p-6">
                <div className="flex items-baseline justify-between">
                  <h3 className="font-display text-2xl">Insights</h3>
                  <span className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">Live</span>
                </div>
                <ul className="mt-4 space-y-3">
                  {data.recent_insights.length === 0 && (
                    <li className="text-sm text-muted-foreground">No insights yet. Upload financial data to generate insights.</li>
                  )}
                  {data.recent_insights.map((s, i) => (
                    <li key={i} className="text-sm leading-relaxed">
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function AgentRunPanel() {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [schedule, setSchedule] = useState("");

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: () => SettingsAPI.get(),
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (settings) {
      setEmail(settings.report_email ?? "");
      setSchedule(settings.report_schedule ?? "");
    }
  }, [settings]);

  const persist = useMutation({
    mutationFn: () =>
      SettingsAPI.update({
        report_email: email.trim() || null,
        report_schedule: schedule || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Report email & schedule saved");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const run = useMutation({
    mutationFn: () => AgentAPI.run(email.trim() || null),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (res.success) toast.success(res.message);
      else toast.error(res.message);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-display text-2xl">AI Agent</h3>
          <p className="mt-1 text-xs text-muted-foreground">
            Run the CFO agent on your uploaded sheets — ingest, detect budget breaches, generate the executive PDF and
            email it. Add a daily schedule to run it automatically.
          </p>
        </div>
        <Button size="sm" onClick={() => run.mutate()} disabled={run.isPending || persist.isPending}>
          {run.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          Run agent
        </Button>
      </div>

      <div className="mt-5 grid gap-4 md:grid-cols-[1fr_200px_auto] md:items-end">
        <div className="space-y-2">
          <Label htmlFor="agent-email" className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
            Report email
          </Label>
          <div className="relative">
            <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="agent-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="finance@company.com"
              className="pl-9"
            />
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="agent-schedule" className="text-xs uppercase tracking-[0.14em] text-muted-foreground">
            Daily schedule (HH:MM)
          </Label>
          <div className="relative">
            <Clock className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="agent-schedule"
              type="time"
              value={schedule}
              onChange={(e) => setSchedule(e.target.value)}
              className="pl-9 num"
            />
          </div>
        </div>

        <Button variant="outline" size="sm" onClick={() => persist.mutate()} disabled={persist.isPending}>
          {persist.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
          Save email & schedule
        </Button>
      </div>

      {run.data && (
        <ul className="mt-5 divide-y divide-border rounded-lg border border-border text-sm">
          {run.data.steps.map((s, i) => (
            <li key={i} className="flex gap-3 px-4 py-2.5">
              <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full bg-success" />
              <div className="min-w-0">
                <p className="font-medium capitalize">{s.step}</p>
                <p className="truncate text-xs text-muted-foreground">{s.message}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function KPI({ label, value, trend, invert }: { label: string; value: string; trend: { text: string; is_positive: boolean }; invert?: boolean }) {
  const positive = invert ? !trend.is_positive : trend.is_positive;
  return (
    <div className="bg-card p-6">
      <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{label}</p>
      <p className="mt-3 font-display text-3xl num">{value}</p>
      <div className="mt-2 flex items-center gap-2 text-xs">
        <span className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 num ${positive ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive"}`}>
          {positive ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
          {trend.text}
        </span>
      </div>
    </div>
  );
}

function CashCard({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{label}</p>
      <p className={`mt-1 font-display text-2xl num ${tone}`}>{value}</p>
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5 text-muted-foreground">
      <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </div>
  );
}

const tooltipStyle = {
  background: "var(--color-card)",
  border: "1px solid var(--color-border)",
  borderRadius: "8px",
  fontSize: "12px",
} as const;
