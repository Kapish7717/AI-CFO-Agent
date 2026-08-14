import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ProvidersAPI, SettingsAPI } from "@/lib/api";
import { toast } from "sonner";

export const Route = createFileRoute("/settings")({
  head: () => ({
    meta: [
      { title: "AI Settings — AI CFO" },
      { name: "description", content: "Configure department budgets and workspace preferences for the AI CFO agent." },
      { property: "og:title", content: "AI Settings — AI CFO" },
      { property: "og:description", content: "Configure the AI CFO workspace." },
    ],
  }),
  component: Settings,
});

function Settings() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: () => SettingsAPI.get(),
    refetchOnWindowFocus: false,
  });

  const [marketing, setMarketing] = useState("");
  const [operations, setOperations] = useState("");
  const [travel, setTravel] = useState("");
  const [primaryProvider, setPrimaryProvider] = useState("");
  const [primaryModel, setPrimaryModel] = useState("");
  const [primaryApiKey, setPrimaryApiKey] = useState("");
  const [fallbackProvider, setFallbackProvider] = useState("");
  const [fallbackModel, setFallbackModel] = useState("");
  const [fallbackApiKey, setFallbackApiKey] = useState("");

  const { data: providers } = useQuery({
    queryKey: ["providers"],
    queryFn: () => ProvidersAPI.list(),
    refetchOnWindowFocus: false,
  });

  const { data: primaryModels, isLoading: primaryModelsLoading } = useQuery({
    queryKey: ["models", primaryProvider, primaryApiKey],
    queryFn: () => ProvidersAPI.models(primaryProvider, primaryApiKey || undefined),
    enabled: !!primaryProvider && primaryProvider !== "none",
    refetchOnWindowFocus: false,
  });

  const { data: fallbackModels, isLoading: fallbackModelsLoading } = useQuery({
    queryKey: ["models", fallbackProvider, fallbackApiKey],
    queryFn: () => ProvidersAPI.models(fallbackProvider, fallbackApiKey || undefined),
    enabled: !!fallbackProvider && fallbackProvider !== "none",
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (data) {
      setMarketing(String(data.budget_marketing ?? ""));
      setOperations(String(data.budget_operations ?? ""));
      setTravel(String(data.budget_travel ?? ""));
      setPrimaryProvider(data.llm_primary_provider ?? "mock");
      setPrimaryModel(data.llm_primary_model ?? "");
      setPrimaryApiKey(data.api_key ?? "");
      setFallbackProvider(data.llm_fallback_provider ?? "");
      setFallbackModel(data.llm_fallback_model ?? "");
      setFallbackApiKey(data.fallback_api_key ?? "");
    }
  }, [data]);

  const save = useMutation({
    mutationFn: () =>
      SettingsAPI.update({
        budget_marketing: parseFloat(marketing) || 0,
        budget_operations: parseFloat(operations) || 0,
        budget_travel: parseFloat(travel) || 0,
        llm_primary_provider: primaryProvider || "mock",
        llm_primary_model: primaryModel || null,
        llm_fallback_provider: fallbackProvider === "none" ? null : fallbackProvider || null,
        llm_fallback_model: fallbackModel || null,
        api_key: primaryApiKey || null,
        fallback_api_key: fallbackApiKey || null,
      }),
    onSuccess: () => {
      toast.success("Settings saved");
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div>
      <PageHeader
        eyebrow="Configuration"
        title="Workspace settings"
        description="Set department budget caps so the AI CFO can flag overspend automatically. All values are stored per user."
        actions={
          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending || isLoading}>
            {save.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save configuration
          </Button>
        }
      />

      <div className="px-6 py-6 md:px-10 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <Section title="Department budgets" desc="Monthly spend caps used by the anomaly and budget agents.">
            {isLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading…
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-3">
                <BudgetField label="Marketing" value={marketing} onChange={setMarketing} />
                <BudgetField label="Operations" value={operations} onChange={setOperations} />
                <BudgetField label="Travel" value={travel} onChange={setTravel} />
              </div>
            )}
          </Section>

          <Section title="Agent behavior" desc="These options are controlled server-side via the LangGraph agent config.">
            <ul className="divide-y divide-border text-sm">
              <ConfigRow label="Streaming responses" value="Enabled" />
              <ConfigRow label="Tool calling" value="Enabled" />
              <ConfigRow label="Multi-agent routing" value="LangGraph supervisor" />
              <ConfigRow label="Model provider" value={primaryProvider ? primaryProvider : "mock"} />
              {fallbackProvider && fallbackProvider !== "none" && (
                <ConfigRow label="Fallback provider" value={fallbackProvider} />
              )}
            </ul>
          </Section>

          <Section
            title="LLM provider & model"
            desc="Choose the language model the AI CFO agent uses and paste your API key for that provider. Primary is used first; if a call fails, the agent falls back to the secondary provider."
          >
            <div className="grid gap-6 md:grid-cols-2">
              <ProviderFields
                title="Primary provider"
                provider={primaryProvider}
                onProvider={setPrimaryProvider}
                model={primaryModel}
                onModel={setPrimaryModel}
                apiKey={primaryApiKey}
                onApiKey={setPrimaryApiKey}
                providers={providers?.providers ?? []}
                models={primaryModels?.models ?? []}
                modelsLoading={primaryModelsLoading}
              />
              <ProviderFields
                title="Fallback provider"
                provider={fallbackProvider}
                onProvider={setFallbackProvider}
                model={fallbackModel}
                onModel={setFallbackModel}
                apiKey={fallbackApiKey}
                onApiKey={setFallbackApiKey}
                providers={providers?.providers ?? []}
                models={fallbackModels?.models ?? []}
                modelsLoading={fallbackModelsLoading}
                allowNone
              />
            </div>
          </Section>
        </div>

        <aside className="space-y-6">
          <div className="rounded-xl border border-border bg-card p-5">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-success" />
              <h4 className="font-medium">Security</h4>
            </div>
            <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
              <li>• Per-user data isolation</li>
              <li>• API keys stored server-side</li>
              <li>• Google OAuth for integrations</li>
              <li>• Encrypted file storage</li>
            </ul>
          </div>

          <div className="rounded-xl border border-border bg-card p-5">
            <h4 className="font-medium">Current budget</h4>
            <dl className="mt-4 space-y-2 text-sm">
              <Row k="Marketing" v={`$${Number(marketing || 0).toLocaleString()}`} />
              <Row k="Operations" v={`$${Number(operations || 0).toLocaleString()}`} />
              <Row k="Travel" v={`$${Number(travel || 0).toLocaleString()}`} />
              <Row
                k="Total cap"
                v={`$${(
                  (parseFloat(marketing) || 0) +
                  (parseFloat(operations) || 0) +
                  (parseFloat(travel) || 0)
                ).toLocaleString()}`}
              />
            </dl>
          </div>
        </aside>
      </div>
    </div>
  );
}

function BudgetField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="space-y-2">
      <Label className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{label}</Label>
      <div className="relative">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">$</span>
        <Input
          type="number"
          min={0}
          step={100}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="pl-7 num"
        />
      </div>
    </div>
  );
}

function ProviderFields({
  title,
  provider,
  onProvider,
  model,
  onModel,
  apiKey,
  onApiKey,
  providers,
  models,
  modelsLoading,
  allowNone,
}: {
  title: string;
  provider: string;
  onProvider: (v: string) => void;
  model: string;
  onModel: (v: string) => void;
  apiKey: string;
  onApiKey: (v: string) => void;
  providers: string[];
  models: string[];
  modelsLoading: boolean;
  allowNone?: boolean;
}) {
  const disabled = !provider || provider === "none";
  const needsKey = !disabled && provider !== "mock" && provider !== "local";
  return (
    <div className="space-y-3">
      <Label className="text-xs uppercase tracking-[0.14em] text-muted-foreground">{title}</Label>
      <Select value={provider} onValueChange={onProvider}>
        <SelectTrigger className="w-full">
          <SelectValue placeholder="Choose provider" />
        </SelectTrigger>
        <SelectContent>
          {allowNone && <SelectItem value="none">None (no fallback)</SelectItem>}
          {providers.map((p) => (
            <SelectItem key={p} value={p}>
              {p}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {needsKey && (
        <div className="space-y-1.5">
          <Input
            type="password"
            value={apiKey}
            onChange={(e) => onApiKey(e.target.value)}
            placeholder="Paste your API key for this provider"
            className="font-mono text-xs"
          />
          <p className="text-xs text-muted-foreground">
            Stored server-side for your account. The agent uses this key instead of the default Groq key.
          </p>
        </div>
      )}
      {disabled ? (
        <div className="rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
          {allowNone ? "Fallback disabled" : "Choose a provider to select a model"}
        </div>
      ) : models.length ? (
        <Select value={model} onValueChange={onModel}>
          <SelectTrigger className="w-full">
            <SelectValue placeholder={modelsLoading ? "Loading…" : "Choose model"} />
          </SelectTrigger>
          <SelectContent>
            {models.map((m) => (
              <SelectItem key={m} value={m}>
                {m}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <Input
          value={model}
          onChange={(e) => onModel(e.target.value)}
          placeholder={modelsLoading ? "Loading models…" : "Model name"}
          className="font-mono text-xs"
        />
      )}
    </div>
  );
}

function Section({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card p-6">
      <div className="mb-5">
        <h3 className="font-display text-xl">{title}</h3>
        {desc && <p className="mt-1 text-xs text-muted-foreground">{desc}</p>}
      </div>
      {children}
    </div>
  );
}

function ConfigRow({ label, value }: { label: string; value: string }) {
  return (
    <li className="flex items-center justify-between py-3">
      <span className="text-sm">{label}</span>
      <span className="text-xs text-muted-foreground">{value}</span>
    </li>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-2 border-b border-border pb-2 last:border-0">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="font-medium truncate num">{v}</dd>
    </div>
  );
}
