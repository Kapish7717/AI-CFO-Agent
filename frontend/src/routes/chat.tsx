import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ArrowUp, Loader2, Bot, User, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AgentAPI, ChatAPI, type ChatMessage } from "@/lib/api";
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
  });

  const [messages, setMessages] = useState<Msg[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Load history once
  useEffect(() => {
    if (history && !historyLoaded) {
      setMessages(
        history.map((m) => ({ id: uid(), sender: m.sender, text: m.text })),
      );
      setHistoryLoaded(true);
    }
  }, [history, historyLoaded]);

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, messages[messages.length - 1]?.text]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
  }, [input]);

  const send = async () => {
    const prompt = input.trim();
    if (!prompt || busy) return;
    setInput("");
    setBusy(true);

    const userMsg: Msg = { id: uid(), sender: "user", text: prompt };
    const agentMsg: Msg = { id: uid(), sender: "agent", text: "", streaming: true };

    setMessages((prev) => [...prev, userMsg, agentMsg]);

    try {
      const res = await AgentAPI.dataQuery(prompt);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === agentMsg.id
            ? { ...m, text: res.answer || "(no response)", streaming: false }
            : m,
        ),
      );
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
  };

  const clearChat = async () => {
    try {
      await ChatAPI.clearHistory();
      setMessages([]);
      qc.setQueryData(["chat-history"], []);
      toast.success("Chat cleared");
    } catch {
      toast.error("Failed to clear chat");
    }
  };

  const hasMessages = messages.length > 0;

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col bg-background">
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl px-4 py-6 md:px-6">
          {isLoading && !historyLoaded && (
            <div className="flex justify-center py-12">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          )}

          {!isLoading && !hasMessages && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/10">
                <Bot className="h-7 w-7 text-accent" />
              </div>
              <h2 className="text-lg font-medium text-foreground">How can I help?</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Ask anything about your financial data.
              </p>
            </div>
          )}

          {hasMessages && (
            <div className="flex justify-end mb-4">
              <button
                onClick={clearChat}
                disabled={busy}
                className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition disabled:opacity-40"
              >
                <Trash2 className="h-3 w-3" />
                Clear chat
              </button>
            </div>
          )}

          <div className="space-y-4">
            {messages.map((m) => (
              <Message key={m.id} {...m} />
            ))}
          </div>
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="border-t border-border bg-background/80 backdrop-blur">
        <div className="mx-auto max-w-2xl px-4 py-3 md:px-6">
          {!hasMessages && (
            <div className="mb-2.5 flex flex-wrap gap-1.5">
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => setInput(s)}
                  disabled={busy}
                  className="rounded-full border border-border bg-muted/50 px-3 py-1 text-xs text-muted-foreground transition hover:border-accent/50 hover:text-foreground disabled:opacity-40"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-end gap-2 rounded-xl border border-border bg-card p-1.5 shadow-sm focus-within:border-accent/50 focus-within:ring-1 focus-within:ring-accent/20 transition-all">
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
              className="min-h-[36px] flex-1 resize-none bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted-foreground/60 disabled:opacity-50"
            />
            <Button
              size="icon"
              className="h-9 w-9 shrink-0 rounded-lg"
              onClick={send}
              disabled={busy || !input.trim()}
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
            </Button>
          </div>
          <p className="mt-2 text-center text-[11px] text-muted-foreground/50">
            AI-generated responses may contain errors. Verify critical data.
          </p>
        </div>
      </div>
    </div>
  );
}

function Message({ sender, text, streaming }: Msg) {
  if (sender === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[75%] flex items-start gap-2.5 flex-row-reverse">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground mt-0.5">
            <User className="h-3.5 w-3.5" />
          </div>
          <div className="rounded-2xl rounded-tr-md bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground whitespace-pre-wrap">
            {text}
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-2.5">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent/10 text-accent mt-0.5">
        <Bot className="h-3.5 w-3.5" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="rounded-2xl rounded-tl-md border border-border bg-card px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap">
          {text || (streaming ? (
            <span className="inline-flex gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-bounce [animation-delay:-0.3s]" />
              <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-bounce [animation-delay:-0.15s]" />
              <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40 animate-bounce" />
            </span>
          ) : "")}
        </div>
      </div>
    </div>
  );
}
