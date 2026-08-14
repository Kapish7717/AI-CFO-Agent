import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { AuthAPI } from "@/lib/api";
import { toast } from "sonner";

export const Route = createFileRoute("/integrations")({
  head: () => ({
    meta: [
      { title: "Integrations — AI CFO" },
      { name: "description", content: "Connect Google Workspace and other productivity tools for the AI CFO to access." },
      { property: "og:title", content: "Integrations — AI CFO" },
      { property: "og:description", content: "Enterprise integrations for AI CFO." },
    ],
  }),
  component: Integrations,
});

const catalog = [
  { name: "PostgreSQL", category: "Database", available: false },
  { name: "MySQL", category: "Database", available: false },
  { name: "Snowflake", category: "Warehouse", available: false },
  { name: "BigQuery", category: "Warehouse", available: false },
  { name: "QuickBooks", category: "Accounting", available: false },
  { name: "Xero", category: "Accounting", available: false },
  { name: "Stripe", category: "Payments", available: false },
  { name: "Razorpay", category: "Payments", available: false },
  { name: "Dropbox", category: "Storage", available: false },
  { name: "OneDrive", category: "Storage", available: false },
  { name: "Slack", category: "Productivity", available: false },
  { name: "Microsoft Teams", category: "Productivity", available: false },
];

function Integrations() {
  const qc = useQueryClient();
  const { data: googleStatus, isLoading } = useQuery({
    queryKey: ["google-status"],
    queryFn: () => AuthAPI.googleStatus(),
    refetchOnWindowFocus: true,
  });

  const popupRef = useRef<Window | null>(null);
  const pollRef = useRef<number | null>(null);

  // Re-check status when the OAuth popup closes.
  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const connect = useMutation({
    mutationFn: () => AuthAPI.googleAuthUrl(),
    onSuccess: (res) => {
      const popup = window.open(res.url, "google-oauth", "width=520,height=680");
      if (!popup) {
        toast.error("Popup blocked. Please allow popups for this site.");
        return;
      }
      popupRef.current = popup;
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = window.setInterval(() => {
        if (popup.closed) {
          if (pollRef.current) window.clearInterval(pollRef.current);
          pollRef.current = null;
          qc.invalidateQueries({ queryKey: ["google-status"] });
        }
      }, 750);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const disconnect = useMutation({
    mutationFn: () => AuthAPI.googleDisconnect(),
    onSuccess: () => {
      toast.success("Google account disconnected");
      qc.invalidateQueries({ queryKey: ["google-status"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const connected = !!googleStatus?.authenticated;

  const grouped = catalog.reduce<Record<string, typeof catalog>>((acc, item) => {
    (acc[item.category] ||= []).push(item);
    return acc;
  }, {});

  return (
    <div>
      <PageHeader
        eyebrow="Integrations"
        title="Connect your entire financial stack"
        description="OAuth-based connectors for platforms. Encrypted credentials, scoped tokens, and audit trails."
      />

      <div className="px-6 py-6 md:px-10 space-y-10">
        <section>
          <h3 className="font-display text-xl mb-4">Google Workspace</h3>
          <div className="rounded-xl border border-border bg-card p-5">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-3 min-w-0">
                <div className="h-10 w-10 rounded-md bg-secondary flex items-center justify-center text-sm font-semibold">G</div>
                <div className="min-w-0">
                  <p className="font-medium">Google account</p>
                  <p className="text-xs text-muted-foreground">
                    {isLoading ? "Checking…" : connected ? "Connected · Gmail, Drive access enabled" : "Not connected"}
                  </p>
                </div>
              </div>
              {connected ? (
                <Button size="sm" variant="outline" onClick={() => disconnect.mutate()} disabled={disconnect.isPending}>
                  {disconnect.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Disconnect
                </Button>
              ) : (
                <Button size="sm" onClick={() => connect.mutate()} disabled={connect.isPending}>
                  {connect.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Connect
                </Button>
              )}
            </div>
          </div>
        </section>

        {Object.entries(grouped).map(([cat, items]) => (
          <section key={cat}>
            <div className="flex items-baseline justify-between mb-4">
              <h3 className="font-display text-xl">{cat}</h3>
              <span className="text-xs text-muted-foreground">Coming soon</span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((i) => (
                <div key={i.name} className="flex items-center justify-between rounded-xl border border-border bg-card p-4 opacity-60">
                  <div className="flex items-center gap-3">
                    <div className="h-9 w-9 rounded-md bg-secondary flex items-center justify-center text-xs font-semibold">
                      {i.name.slice(0, 2).toUpperCase()}
                    </div>
                    <div>
                      <p className="font-medium text-sm">{i.name}</p>
                      <p className="text-[11px] text-muted-foreground">Not connected</p>
                    </div>
                  </div>
                  <Button size="sm" variant="outline" disabled>Soon</Button>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
