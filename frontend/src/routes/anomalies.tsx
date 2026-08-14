import { createFileRoute } from "@tanstack/react-router";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { anomalies } from "@/lib/mock-data";
import { AlertTriangle } from "lucide-react";

export const Route = createFileRoute("/anomalies")({
  head: () => ({
    meta: [
      { title: "Anomalies — AI CFO" },
      { name: "description", content: "Detect duplicate invoices, suspicious transactions, and vendor risk with an always-on fraud agent." },
      { property: "og:title", content: "Anomalies — AI CFO" },
      { property: "og:description", content: "Autonomous fraud and anomaly detection." },
    ],
  }),
  component: Anomalies,
});

function Anomalies() {
  const stats = [
    { label: "Open", value: anomalies.length, tone: "text-foreground" },
    { label: "High severity", value: anomalies.filter(a => a.severity === "high").length, tone: "text-destructive" },
    { label: "Exposure", value: "$72.6K", tone: "text-foreground" },
    { label: "Mean time to review", value: "3.2 hr", tone: "text-foreground" },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Risk"
        title="Anomaly & fraud signals"
        description="The Fraud Agent scans every transaction against historical baselines, duplicate heuristics, and vendor risk models."
        actions={<Button size="sm" variant="outline">Configure rules</Button>}
      />

      <div className="px-6 py-6 md:px-10 space-y-6">
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-4">
          {stats.map((s) => (
            <div key={s.label} className="bg-card p-5">
              <p className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{s.label}</p>
              <p className={`mt-2 font-display text-2xl num ${s.tone}`}>{s.value}</p>
            </div>
          ))}
        </div>

        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-5 py-4">
            <h3 className="font-display text-xl flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-warning" />
              Open cases
            </h3>
            <span className="text-xs text-muted-foreground">Sorted by severity</span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-[0.14em] text-muted-foreground border-b border-border">
                <th className="px-5 py-3 font-medium">ID</th>
                <th className="px-5 py-3 font-medium">Vendor</th>
                <th className="px-5 py-3 font-medium">Reason</th>
                <th className="px-5 py-3 font-medium text-right">Amount</th>
                <th className="px-5 py-3 font-medium">Detected</th>
                <th className="px-5 py-3 font-medium">Severity</th>
                <th className="px-5 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {anomalies.map((a) => (
                <tr key={a.id} className="hover:bg-muted/40 transition">
                  <td className="px-5 py-4 font-mono text-xs text-muted-foreground">{a.id}</td>
                  <td className="px-5 py-4 font-medium">{a.vendor}</td>
                  <td className="px-5 py-4 text-muted-foreground max-w-md">{a.reason}</td>
                  <td className="px-5 py-4 text-right num">{a.amount}</td>
                  <td className="px-5 py-4 text-muted-foreground">{a.date}</td>
                  <td className="px-5 py-4">
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      a.severity === "high" ? "bg-destructive/10 text-destructive" :
                      a.severity === "medium" ? "bg-warning/15 text-warning-foreground" :
                      "bg-muted text-muted-foreground"
                    }`}>
                      <span className={`h-1.5 w-1.5 rounded-full ${
                        a.severity === "high" ? "bg-destructive" :
                        a.severity === "medium" ? "bg-warning" : "bg-muted-foreground"
                      }`} />
                      {a.severity}
                    </span>
                  </td>
                  <td className="px-5 py-4 text-right">
                    <Button size="sm" variant="ghost">Review</Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
