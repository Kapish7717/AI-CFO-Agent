import { createFileRoute } from "@tanstack/react-router";
import { Area, AreaChart, CartesianGrid, Legend as RLegend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { forecastSeries } from "@/lib/mock-data";

export const Route = createFileRoute("/forecasts")({
  head: () => ({
    meta: [
      { title: "Forecasts — AI CFO" },
      { name: "description", content: "AI-generated revenue, expense, and cash-flow forecasts with scenario modeling and confidence bands." },
      { property: "og:title", content: "Forecasts — AI CFO" },
      { property: "og:description", content: "AI-generated financial forecasts with scenarios." },
    ],
  }),
  component: Forecasts,
});

const scenarios = [
  { name: "Base Case", revenue: "$16.8M", growth: "+18%", note: "Current trajectory holds" },
  { name: "Aggressive Hiring", revenue: "$18.2M", growth: "+28%", note: "+12 GTM hires in Q4" },
  { name: "Downturn", revenue: "$14.1M", growth: "+2%", note: "20% churn shock, deal slippage" },
];

function Forecasts() {
  return (
    <div>
      <PageHeader
        eyebrow="Predictive"
        title="Forecast horizon: next 4 quarters"
        description="Ensemble models combine time-series, driver-based, and LLM narrative signals. Regenerate anytime."
        actions={<Button size="sm">Regenerate forecast</Button>}
      />

      <div className="px-6 py-6 md:px-10 space-y-8">
        <div className="rounded-xl border border-border bg-card p-6">
          <h3 className="font-display text-2xl">Revenue projection</h3>
          <p className="text-xs text-muted-foreground">Actuals through August · forecast Sep–Dec 2026</p>
          <div className="mt-6 h-80">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={forecastSeries} margin={{ left: -20 }}>
                <defs>
                  <linearGradient id="fc" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--color-accent)" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="var(--color-accent)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--color-border)" vertical={false} />
                <XAxis dataKey="month" stroke="var(--color-muted-foreground)" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="var(--color-muted-foreground)" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ background: "var(--color-card)", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 12 }} />
                <RLegend wrapperStyle={{ fontSize: 12 }} />
                <Area type="monotone" dataKey="revenue" name="Actual" stroke="var(--color-primary)" strokeWidth={2} fill="none" />
                <Area type="monotone" dataKey="forecast" name="Forecast" stroke="var(--color-accent)" strokeWidth={2} strokeDasharray="6 4" fill="url(#fc)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div>
          <h3 className="font-display text-2xl mb-4">Scenario planning</h3>
          <div className="grid gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-3">
            {scenarios.map((s, i) => (
              <div key={s.name} className={`bg-card p-6 ${i === 0 ? "ring-1 ring-accent/40" : ""}`}>
                {i === 0 && <p className="text-[10px] uppercase tracking-[0.2em] text-accent">Recommended</p>}
                <h4 className="mt-1 font-display text-xl">{s.name}</h4>
                <p className="mt-4 num text-3xl">{s.revenue}</p>
                <p className="text-xs text-success num">{s.growth} YoY</p>
                <p className="mt-4 text-sm text-muted-foreground">{s.note}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-6">
          <h3 className="font-display text-2xl">Cash runway sensitivity</h3>
          <p className="text-xs text-muted-foreground">Months of runway at variable burn rates</p>
          <div className="mt-6 h-60">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={[
                { burn: "$180K", months: 22 },
                { burn: "$220K", months: 18 },
                { burn: "$260K", months: 15 },
                { burn: "$300K", months: 13 },
                { burn: "$340K", months: 11 },
                { burn: "$380K", months: 9 },
              ]} margin={{ left: -20 }}>
                <CartesianGrid stroke="var(--color-border)" vertical={false} />
                <XAxis dataKey="burn" stroke="var(--color-muted-foreground)" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="var(--color-muted-foreground)" fontSize={11} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ background: "var(--color-card)", border: "1px solid var(--color-border)", borderRadius: 8, fontSize: 12 }} />
                <Line type="monotone" dataKey="months" stroke="var(--color-accent)" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
