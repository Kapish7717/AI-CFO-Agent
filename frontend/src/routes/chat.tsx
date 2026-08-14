import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/page-header";
import { AgentAPI, ChatAPI, type ChatMessage } from "@/lib/api";
import { toast } from "sonner";

export const Route = createFileRoute("/chat")({
  head: () => ({
    meta: [
      { title: "AI Assistant — AI CFO" },
      { name: "description", content: "Ask questions about your uploaded financial data — revenue, expenses, categories, vendors, and anomalies." },
      { property: "og:title", content: "AI Assistant — AI CFO" },
      { property: "og:description", content: "Query your financial data with natural language." },
    ],
  }),
  component: Chat,
});

const suggestions = [
  "What was our total spend this period?",
  "Which category had the highest expenses?",
  "Are there any flagged anomalies?",
  "Who are our top vendors?",
  "List the latest transactions",
];

interface LiveMessage extends ChatMessage {
  step?: string;
  streaming?: boolean;
}

function Chat() {
  const qc = useQueryClient();
  const { data: history, isLoading } = useQuery({
    queryKey: ["chat-history"],
    queryFn: () => ChatAPI.history(),
    refetchOnWindowFocus: false,
  });

  const [live, setLive] = useState<LiveMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const messages: LiveMessage[] = [...(history ?? []), ...live];

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, currentStep]);

  const send = async () => {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setInput("");
    setBusy(true);
    setCurrentStep("querying");

    const userMsg: LiveMessage = { sender: "user", text: prompt };
    setLive((prev) => [...prev, userMsg]);
    setLive((prev) => [...prev, { sender: "agent", text: "", streaming: true }]);

    try {
      const res = await AgentAPI.dataQuery(prompt);
      const agentText = res.answer || "(no response)";
      setLive((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { sender: "agent", text: agentText, streaming: false };
        return copy;
      });
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["chat-history"] });
        setLive([]);
      }, 250);
    } catch (err: any) {
      toast.error(err?.message || "Chat request failed");
      setLive((prev) => {
        const copy = [...prev];
        copy[copy.length - 1] = { sender: "agent", text: `Error: ${err?.message || "request failed"}`, streaming: false };
        return copy;
      });
    } finally {
      setBusy(false);
      setCurrentStep(null);
    }
  };

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      <PageHeader
        eyebrow="Autonomous CFO"
        title="Ask anything. Get answers with sources."
        description="Backed by Jina RAG over your connected financial data."
      />

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-6 md:px-10">
        <div className="mx-auto max-w-3xl space-y-6">
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading conversation…</div>
          )}
          {messages.map((m, i) => (
            <Message key={i} {...m} />
          ))}
          {busy && currentStep && currentStep !== "agent" && (
            <div className="flex gap-3">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
                <Loader2 className="h-4 w-4 animate-spin" />
              </div>
              <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3 text-xs text-muted-foreground">
                Running <span className="font-mono text-foreground">{currentStep}</span>…
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="border-t border-border bg-background/80 px-6 py-4 md:px-10 backdrop-blur">
        <div className="mx-auto max-w-3xl">
          <div className="mb-3 flex flex-wrap gap-2">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => setInput(s)}
                disabled={busy}
                className="rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground transition hover:border-accent hover:text-foreground disabled:opacity-50"
              >
                {s}
              </button>
            ))}
          </div>
          <div className="flex items-end gap-2 rounded-xl border border-border bg-card p-2 focus-within:border-accent transition">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask about revenue, forecasts, anomalies…"
              rows={1}
              disabled={busy}
              className="flex-1 resize-none bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
            />
            <Button size="icon" className="h-9 w-9 shrink-0" onClick={send} disabled={busy || !input.trim()}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Message({ sender, text, streaming }: LiveMessage) {
  if (sender === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground whitespace-pre-wrap">
          {text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent/15 text-accent">
        <Sparkles className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap">
          {text || (streaming ? "…" : "")}
        </div>
      </div>
    </div>
  );
}
