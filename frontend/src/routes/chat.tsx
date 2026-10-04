import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Loader2, Bot, User, Trash2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AgentAPI, ChatAPI } from "@/lib/api";
import { toast } from "sonner";

export const Route = createFileRoute("/chat")({
  head: () => ({
    meta: [
      { title: "AI Chat — AI CFO" },
      { name: "description", content: "Ask questions about your financial data." },
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

interface Msg {
  id: string;
  sender: "user" | "agent";
  text: string;
  streaming?: boolean;
}

let _id = 0;
const uid = () => `${++_id}-${Date.now()}`;

function Chat() {
  const qc = useQueryClient();

  const { data: history, isLoading } = useQuery({
    queryKey: ["chat-history"],
    queryFn: () => ChatAPI.history(),
    refetchOnWindowFocus: false,
    refetchOnMount: true,
  });

  const [messages, setMessages] = useState<Msg[]>([]);
  const historyLoadedRef = useRef(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load history once — sort by ISO timestamp + id for deterministic ordering
  useEffect(() => {
    if (history && !historyLoadedRef.current) {
      historyLoadedRef.current = true;
      const sorted = [...history].sort((a, b) => {
        // Compare full ISO timestamps lexicographically (YYYY-MM-DDTHH:MM:SS sorts correctly)
        const ta = a.timestamp || "";
        const tb = b.timestamp || "";
        if (ta !== tb) return ta < tb ? -1 : ta > tb ? 1 : 0;
        // Tie-break by id (always ascending = insertion order)
        return (a.id ?? 0) - (b.id ?? 0);
      });
      setMessages(
        sorted.map((m) => ({
          id: uid(),
          sender: m.sender,
          text: m.text,
        })),
      );
    }
  }, [history]);

  // Reset the ref when component truly unmounts (e.g. full page nav)
  useEffect(() => {
    return () => {
      historyLoadedRef.current = false;
    };
  }, []);

  // Auto-scroll
  const lastText = messages[messages.length - 1]?.text;
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, lastText]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
  }, [input]);

  const send = useCallback(async () => {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setInput("");
    setBusy(true);

    const userMsg: Msg = { id: uid(), sender: "user", text: prompt };
    const agentMsg: Msg = { id: uid(), sender: "agent", text: "", streaming: true };

    setMessages((prev) => [...prev, userMsg, agentMsg]);

    try {
      let accumulated = "";
      for await (const chunk of AgentAPI.dataQueryStream(prompt)) {
        accumulated += chunk;
        const snap = accumulated;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === agentMsg.id ? { ...m, text: snap } : m,
          ),
        );
      }
      setMessages((prev) =>
        prev.map((m) =>
          m.id === agentMsg.id ? { ...m, streaming: false } : m,
        ),
      );
      // Invalidate so next mount fetches fresh history
      qc.invalidateQueries({ queryKey: ["chat-history"] });
    } catch (err: any) {
      toast.error(err?.message || "Chat request failed");
      setMessages((prev) =>
        prev.map((m) =>
          m.id === agentMsg.id
            ? { ...m, text: `Error: ${err?.message || "request failed"}`, streaming: false }
            : m,
        ),
      );
    } finally {
      setBusy(false);
    }
  }, [input, busy, qc]);

  const clearChat = async () => {
    try {
      await ChatAPI.clearHistory();
      setMessages([]);
      qc.setQueryData(["chat-history"], []);
      historyLoadedRef.current = false;
      toast.success("Chat cleared");
    } catch {
      toast.error("Failed to clear chat");
    }
  };

  const hasMessages = messages.length > 0;

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col bg-background">
      {/* Messages area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl px-4 py-6 md:px-6">
          {isLoading && messages.length === 0 && (
            <div className="flex justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}

          {/* Empty state */}
          {!isLoading && !hasMessages && (
            <div className="flex flex-col items-center justify-center py-24 text-center">
              <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-accent/20 to-accent/5 shadow-sm">
                <Sparkles className="h-8 w-8 text-accent" />
              </div>
              <h2 className="text-xl font-semibold text-foreground">How can I help?</h2>
              <p className="mt-1.5 text-sm text-muted-foreground max-w-xs">
                Ask anything about your financial data and get instant insights.
              </p>
            </div>
          )}

          {/* Clear chat button */}
          {hasMessages && (
            <div className="flex justify-end mb-4">
              <button
                onClick={clearChat}
                disabled={busy}
                className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors disabled:opacity-40"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Clear chat
              </button>
            </div>
          )}

          {/* Messages */}
          <div className="space-y-4">
            {messages.map((m) => (
              <MessageBubble key={m.id} {...m} />
            ))}
          </div>
          <div ref={bottomRef} className="h-1" />
        </div>
      </div>

      {/* Input area */}
      <div className="border-t border-border/60 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
        <div className="mx-auto max-w-2xl px-4 py-3 md:px-6">
          {/* Suggestion chips */}
          {!hasMessages && (
            <div className="mb-3 flex flex-wrap gap-1.5">
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => setInput(s)}
                  disabled={busy}
                  className="rounded-full border border-border/80 bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground transition-all hover:border-accent/40 hover:bg-accent/5 hover:text-foreground disabled:opacity-40"
                >
                  {s}
                </button>
              ))}
            </div>
          )}

          {/* Input box */}
          <div className="flex items-end gap-2 rounded-2xl border border-border/60 bg-card p-2 shadow-sm transition-all focus-within:border-accent/40 focus-within:shadow-md focus-within:ring-1 focus-within:ring-accent/10">
            <textarea
              ref={textareaRef}
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
              className="min-h-[40px] flex-1 resize-none bg-transparent px-3 py-2 text-sm leading-relaxed outline-none placeholder:text-muted-foreground/50 disabled:opacity-50"
            />
            <Button
              size="icon"
              className="h-9 w-9 shrink-0 rounded-xl bg-accent hover:bg-accent/90 text-accent-foreground shadow-sm"
              onClick={send}
              disabled={busy || !input.trim()}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ArrowUp className="h-4 w-4" strokeWidth={2.5} />
              )}
            </Button>
          </div>
          <p className="mt-2 text-center text-[11px] text-muted-foreground/40">
            AI-generated responses may contain errors. Verify critical data.
          </p>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ sender, text, streaming }: Msg) {
  const isUser = sender === "user";

  if (isUser) {
    return (
      <div className="flex justify-end animate-in fade-in slide-in-from-bottom-2 duration-200">
        <div className="flex max-w-[80%] items-end gap-2.5 flex-row-reverse">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-sm">
            <User className="h-4 w-4" />
          </div>
          <div className="rounded-2xl rounded-br-md bg-primary px-4 py-3 text-sm leading-relaxed text-primary-foreground whitespace-pre-wrap shadow-sm">
            {text}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start animate-in fade-in slide-in-from-bottom-2 duration-200">
      <div className="flex max-w-[80%] items-end gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-accent/15 to-accent/5 text-accent shadow-sm ring-1 ring-accent/10">
          <Bot className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="rounded-2xl rounded-bl-md border border-border/60 bg-card px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap shadow-sm">
            {text || (streaming ? (
              <span className="inline-flex items-center gap-1.5 py-0.5">
                <span className="h-1.5 w-1.5 rounded-full bg-accent/50 animate-bounce [animation-delay:-0.3s]" />
                <span className="h-1.5 w-1.5 rounded-full bg-accent/50 animate-bounce [animation-delay:-0.15s]" />
                <span className="h-1.5 w-1.5 rounded-full bg-accent/50 animate-bounce" />
              </span>
            ) : (
              <span className="text-muted-foreground/40 italic">No response</span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
