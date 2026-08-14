import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Database,
  FileSpreadsheet,
  Mail,
  CreditCard,
  Cloud,
  Plug,
  Plus,
  RefreshCw,
  Loader2,
  Upload,
  CheckCircle2,
  FileUp,
} from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { dataSources as seedSources } from "@/lib/mock-data";
import { UploadAPI, StripeAPI } from "@/lib/api";
import { toast } from "sonner";

export const Route = createFileRoute("/data-sources")({
  head: () => ({
    meta: [
      { title: "Data Sources — AI CFO" },
      {
        name: "description",
        content:
          "Connect databases, accounting suites, payment processors and file stores. Every source is normalized into one transaction schema.",
      },
      { property: "og:title", content: "Data Sources — AI CFO" },
      {
        property: "og:description",
        content: "Unified ingestion pipeline for all financial data.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: DataSources,
});

type Connector = {
  id: string;
  name: string;
  category: string;
  icon: React.ComponentType<{ className?: string }>;
  fields: { key: string; label: string; placeholder: string; type?: string }[];
};

const connectors: Connector[] = [
  {
    id: "postgres",
    name: "PostgreSQL",
    category: "Database",
    icon: Database,
    fields: [
      { key: "host", label: "Host", placeholder: "db.company.internal" },
      { key: "database", label: "Database", placeholder: "finance_prod" },
      { key: "user", label: "User", placeholder: "readonly" },
      { key: "password", label: "Password", placeholder: "••••••••", type: "password" },
    ],
  },
  {
    id: "snowflake",
    name: "Snowflake",
    category: "Warehouse",
    icon: Database,
    fields: [
      { key: "account", label: "Account", placeholder: "xy12345.eu-central-1" },
      { key: "warehouse", label: "Warehouse", placeholder: "COMPUTE_WH" },
      { key: "token", label: "Access token", placeholder: "••••••••", type: "password" },
    ],
  },
  {
    id: "quickbooks",
    name: "QuickBooks",
    category: "Accounting",
    icon: FileSpreadsheet,
    fields: [{ key: "realm", label: "Company / realm ID", placeholder: "4620816365..." }],
  },
  {
    id: "xero",
    name: "Xero",
    category: "Accounting",
    icon: FileSpreadsheet,
    fields: [{ key: "tenant", label: "Tenant ID", placeholder: "xero-tenant-id" }],
  },
  {
    id: "stripe",
    name: "Stripe",
    category: "Payments",
    icon: CreditCard,
    fields: [{ key: "key", label: "Restricted API key", placeholder: "rk_live_…", type: "password" }],
  },
  {
    id: "razorpay",
    name: "Razorpay",
    category: "Payments",
    icon: CreditCard,
    fields: [
      { key: "key_id", label: "Key ID", placeholder: "rzp_live_…" },
      { key: "secret", label: "Key secret", placeholder: "••••••••", type: "password" },
    ],
  },
  {
    id: "gmail",
    name: "Gmail Invoices",
    category: "Email",
    icon: Mail,
    fields: [{ key: "label", label: "Gmail label to watch", placeholder: "Invoices/2026" }],
  },
  {
    id: "drive",
    name: "Google Drive",
    category: "Storage",
    icon: Cloud,
    fields: [{ key: "folder", label: "Folder ID", placeholder: "1AbC…" }],
  },
  {
    id: "dropbox",
    name: "Dropbox",
    category: "Storage",
    icon: Cloud,
    fields: [{ key: "path", label: "Folder path", placeholder: "/Finance/Statements" }],
  },
];

const statusStyles: Record<string, string> = {
  healthy: "bg-success/10 text-success",
  syncing: "bg-muted text-muted-foreground",
  error: "bg-destructive/10 text-destructive",
};

function DataSources() {
  const qc = useQueryClient();
  const [sources, setSources] = useState(seedSources);
  const [active, setActive] = useState<Connector | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [connecting, setConnecting] = useState(false);

  const expenseInputRef = useRef<HTMLInputElement>(null);
  const revenueInputRef = useRef<HTMLInputElement>(null);
  const [uploaded, setUploaded] = useState<Record<"expense" | "revenue", string | null>>({
    expense: null,
    revenue: null,
  });

  const upload = useMutation({
    mutationFn: ({ file, fileType }: { file: File; fileType: "expense" | "revenue" }) =>
      UploadAPI.file(file, fileType),
    onSuccess: (res, { fileType }) => {
      if (res.error) {
        toast.error(res.error);
        return;
      }
      setUploaded((prev) => ({ ...prev, [fileType]: res.filename ?? null }));
      toast.success(
        `${fileType === "expense" ? "Expense" : "Revenue"} sheet uploaded to cloud storage`,
      );
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  function handleFile(fileType: "expense" | "revenue", file: File | undefined) {
    if (!file) return;
    upload.mutate({ file, fileType });
  }

  const { data: stripeStatus } = useQuery({
    queryKey: ["stripe-status"],
    queryFn: () => StripeAPI.status(),
    refetchOnWindowFocus: true,
  });
  const stripeConnected = !!stripeStatus?.connected;

  const stripeConnect = useMutation({
    mutationFn: () => StripeAPI.connect(values.key ?? ""),
    onSuccess: (res) => {
      if (res.error) {
        toast.error(res.error);
        setActive(null);
        return;
      }
      setSources((prev) => [
        {
          name: "Stripe",
          type: "Payments",
          records: String(res.total),
          status: "healthy",
          synced: "just now",
        },
        ...prev,
      ]);
      setActive(null);
      toast.success(`Stripe connected — ${res.synced} transactions synced`);
      qc.invalidateQueries({ queryKey: ["stripe-status"] });
    },
    onError: (e: Error) => {
      setActive(null);
      toast.error(e.message);
    },
  });

  const stripeDisconnect = useMutation({
    mutationFn: () => StripeAPI.disconnect(),
    onSuccess: () => {
      toast.success("Stripe disconnected");
      qc.invalidateQueries({ queryKey: ["stripe-status"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const grouped = useMemo(
    () =>
      connectors.reduce<Record<string, Connector[]>>((acc, c) => {
        (acc[c.category] ||= []).push(c);
        return acc;
      }, {}),
    [],
  );

  function openConnector(c: Connector) {
    setActive(c);
    setValues({});
  }

  function submit() {
    if (!active) return;
    if (active.id === "stripe") {
      stripeConnect.mutate();
      return;
    }
    setConnecting(true);
    window.setTimeout(() => {
      setSources((prev) => [
        {
          name: active.name,
          type: active.category,
          records: "—",
          status: "syncing",
          synced: "in progress",
        },
        ...prev,
      ]);
      setConnecting(false);
      setActive(null);
      toast.success(`${active.name} connected — initial sync started`);
    }, 900);
  }

  return (
    <div>
      <PageHeader
        eyebrow="Connectors"
        title="Financial data, normalized"
        description="Connect databases, ledgers, payment processors and file stores. Every source flows through the Connector Manager — authenticated, validated, and translated to a unified transaction schema."
        actions={
          <Button size="sm" onClick={() => openConnector(connectors[0])}>
            <Plus className="h-4 w-4" /> Connect source
          </Button>
        }
      />

      <div className="px-6 py-6 md:px-10 space-y-10">
        <section>
          <div className="flex items-baseline justify-between mb-4">
            <h2 className="font-display text-xl">Upload financial sheets</h2>
            <span className="text-xs text-muted-foreground">CSV · XLS · XLSX · PDF → Supabase</span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <UploadCard
              title="Expense sheet"
              description="Vendor spend, operating costs and category-level expenses."
              filename={uploaded.expense}
              uploading={upload.isPending && upload.variables?.fileType === "expense"}
              inputRef={expenseInputRef}
              onPick={() => expenseInputRef.current?.click()}
              onFile={(f) => handleFile("expense", f)}
            />
            <UploadCard
              title="Revenue sheet"
              description="Invoices, sales, income and cash inflow transactions."
              filename={uploaded.revenue}
              uploading={upload.isPending && upload.variables?.fileType === "revenue"}
              inputRef={revenueInputRef}
              onPick={() => revenueInputRef.current?.click()}
              onFile={(f) => handleFile("revenue", f)}
            />
          </div>
        </section>

        <section>
          <div className="flex items-baseline justify-between mb-4">
            <h2 className="font-display text-xl">Connected sources</h2>
            <span className="text-xs text-muted-foreground">{sources.length} active</span>
          </div>
          <div className="overflow-hidden rounded-xl border border-border">
            <table className="w-full text-sm">
              <thead className="bg-secondary/50 text-left text-xs uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="px-4 py-3 font-medium">Source</th>
                  <th className="px-4 py-3 font-medium">Type</th>
                  <th className="px-4 py-3 font-medium">Records</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Last sync</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => (
                  <tr key={s.name} className="border-t border-border">
                    <td className="px-4 py-3 font-medium">{s.name}</td>
                    <td className="px-4 py-3 text-muted-foreground">{s.type}</td>
                    <td className="px-4 py-3 text-muted-foreground">{s.records}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                          statusStyles[s.status] ?? "bg-muted text-muted-foreground"
                        }`}
                      >
                        <span className="h-1.5 w-1.5 rounded-full bg-current" />
                        {s.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{s.synced}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {Object.entries(grouped).map(([category, items]) => (
          <section key={category}>
            <h2 className="font-display text-xl mb-4">{category}</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {items.map((c) => {
                const connected =
                  c.id === "stripe" ? stripeConnected : sources.some((s) => s.name === c.name);
                const Icon = c.icon;
                return (
                  <div
                    key={c.id}
                    className="flex items-center justify-between rounded-xl border border-border bg-card p-4"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="flex h-9 w-9 items-center justify-center rounded-md bg-secondary text-foreground">
                        <Icon className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{c.name}</p>
                        <p className="text-[11px] text-muted-foreground">
                          {connected ? "Connected" : "Not connected"}
                        </p>
                      </div>
                    </div>
                    {c.id === "stripe" && connected ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => stripeDisconnect.mutate()}
                        disabled={stripeDisconnect.isPending}
                      >
                        Disconnect
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant={connected ? "outline" : "default"}
                        onClick={() => openConnector(c)}
                      >
                        {connected ? (
                          <>
                            <RefreshCw className="h-4 w-4" /> Reconnect
                          </>
                        ) : (
                          <>
                            <Plug className="h-4 w-4" /> Connect
                          </>
                        )}
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ))}
      </div>

      <Dialog open={!!active} onOpenChange={(o) => !o && setActive(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Connect {active?.name}</DialogTitle>
            <DialogDescription>
              Credentials are encrypted at rest and scoped to read-only access.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {active?.fields.map((f) => (
              <div key={f.key} className="space-y-1.5">
                <Label htmlFor={f.key}>{f.label}</Label>
                <Input
                  id={f.key}
                  type={f.type ?? "text"}
                  placeholder={f.placeholder}
                  value={values[f.key] ?? ""}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setActive(null)}>
              Cancel
            </Button>
            <Button onClick={submit} disabled={connecting || stripeConnect.isPending}>
              {connecting || stripeConnect.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : null}
              Connect
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function UploadCard({
  title,
  description,
  filename,
  uploading,
  inputRef,
  onPick,
  onFile,
}: {
  title: string;
  description: string;
  filename: string | null;
  uploading: boolean;
  inputRef: React.RefObject<HTMLInputElement | null>;
  onPick: () => void;
  onFile: (file: File) => void;
}) {
  return (
    <div className="flex flex-col justify-between rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-secondary text-foreground">
          <FileSpreadsheet className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="font-medium">{title}</p>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".csv,.xls,.xlsx,.pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />

      <div className="mt-4 flex items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          {filename ? (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-success">
              <CheckCircle2 className="h-3.5 w-3.5" /> {filename}
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
              <FileUp className="h-3.5 w-3.5" /> No file uploaded
            </span>
          )}
        </div>
        <Button size="sm" onClick={onPick} disabled={uploading}>
          {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
          {uploading ? "Uploading…" : "Upload"}
        </Button>
      </div>
    </div>
  );
}
