import { createFileRoute } from "@tanstack/react-router";
import { Download, FileText, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { DashboardAPI } from "@/lib/api";

export const Route = createFileRoute("/reports")({
  head: () => ({
    meta: [
      { title: "Reports — AI CFO" },
      { name: "description", content: "Download the AI CFO executive PDF report generated from your latest financial data." },
      { property: "og:title", content: "Reports — AI CFO" },
      { property: "og:description", content: "Executive-ready AI-generated reports." },
    ],
  }),
  component: Reports,
});

const templates = [
  { title: "Executive Summary", desc: "Board-ready recap with narrative and KPIs" },
  { title: "Forecast & Scenarios", desc: "Base, aggressive, and downside modeling" },
  { title: "Vendor Deep Dive", desc: "Spend concentration and risk analysis" },
  { title: "Cash Flow Digest", desc: "Weekly inflows, outflows, and runway" },
];

function Reports() {
  const reportUrl = DashboardAPI.downloadReportUrl();

  return (
    <div>
      <PageHeader
        eyebrow="Report Center"
        title="Reports written by your AI CFO"
        description="Automated on demand. Ask the AI CFO in chat to generate a fresh executive report, then download the PDF here."
        actions={
          <Button size="sm" asChild>
            <a href="/chat"><Sparkles className="h-4 w-4" /> Generate via chat</a>
          </Button>
        }
      />

      <div className="px-6 py-6 md:px-10 space-y-8">
        <section>
          <h3 className="font-display text-xl mb-4">Latest executive report</h3>
          <div className="rounded-xl border border-border bg-card p-6 flex items-center justify-between gap-4">
            <div className="flex items-center gap-4 min-w-0">
              <div className="h-12 w-12 shrink-0 rounded-md border border-border bg-secondary flex items-center justify-center text-[10px] font-semibold tracking-wider text-muted-foreground">
                PDF
              </div>
              <div className="min-w-0">
                <p className="font-medium">Executive CFO Report</p>
                <p className="text-xs text-muted-foreground">
                  Generated when you run the anomaly + reporting workflow.
                </p>
              </div>
            </div>
            <Button asChild size="sm">
              <a href={reportUrl} download target="_blank" rel="noopener noreferrer">
                <Download className="h-4 w-4" /> Download PDF
              </a>
            </Button>
          </div>
        </section>

        <section>
          <h3 className="font-display text-xl mb-4">Report templates</h3>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {templates.map((t) => (
              <div key={t.title} className="rounded-xl border border-border bg-card p-5">
                <div className="h-8 w-8 rounded-md bg-accent/10 text-accent flex items-center justify-center">
                  <FileText className="h-4 w-4" />
                </div>
                <h4 className="mt-4 font-medium">{t.title}</h4>
                <p className="mt-1 text-xs text-muted-foreground leading-relaxed">{t.desc}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
