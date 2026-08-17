import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2, KeyRound, Loader2, X } from "lucide-react";
import { AuthAPI } from "@/lib/api";
import { Button } from "@/components/ui/button";

const DISMISS_KEY = "aicfo.google-auth-dismissed";

function useDismissed() {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(DISMISS_KEY) === "1";
  });

  const dismiss = () => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(DISMISS_KEY, "1");
    setDismissed(true);
  };

  return { dismissed, dismiss };
}

export function GoogleAuthBar() {
  const qc = useQueryClient();
  const { dismissed, dismiss } = useDismissed();

  const { data: status, isLoading } = useQuery({
    queryKey: ["google-status"],
    queryFn: () => AuthAPI.googleStatus(),
    refetchOnWindowFocus: true,
  });

  const popupRef = useRef<Window | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, []);

  const connect = useMutation({
    mutationFn: () => AuthAPI.googleAuthUrl(),
    onSuccess: (res) => {
      const popup = window.open(res.url, "google-oauth", "width=520,height=680");
      if (!popup) return;
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
  });

  const disconnect = useMutation({
    mutationFn: () => AuthAPI.googleDisconnect(),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["google-status"] });
    },
  });

  const connected = !!status?.authenticated;

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Checking Google authentication…
      </div>
    );
  }

  if (connected) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-success/40 bg-success/5 px-4 py-3">
        <div className="flex items-center gap-2.5 text-sm">
          <CheckCircle2 className="h-4 w-4 text-success" />
          <span className="font-medium text-foreground">Google authenticated</span>
          <span className="hidden text-xs text-muted-foreground sm:inline">
            · Gmail & Calendar access enabled for the AI CFO agent
          </span>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => disconnect.mutate()}
          disabled={disconnect.isPending}
        >
          {disconnect.isPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Disconnect
        </Button>
      </div>
    );
  }

  if (dismissed) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-primary/40 bg-primary/5 px-4 py-3">
      <div className="flex items-center gap-2.5 text-sm">
        <KeyRound className="h-4 w-4 text-primary" />
        <div>
          <p className="font-medium text-foreground">
            Authenticate with Google to unlock the full agent
          </p>
          <p className="text-xs text-muted-foreground">
            Required for emailing PDF reports and scheduling meetings automatically.
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Button size="sm" onClick={() => connect.mutate()} disabled={connect.isPending}>
          {connect.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <KeyRound className="h-4 w-4" />
          )}
          Authenticate
        </Button>
        <Button
          size="icon"
          variant="ghost"
          onClick={dismiss}
          aria-label="Dismiss"
          className="h-8 w-8"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}
