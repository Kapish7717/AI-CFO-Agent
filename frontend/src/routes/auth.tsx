import { createFileRoute, useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/lib/auth";
import { toast } from "sonner";

type AuthSearch = { redirect?: string };

export const Route = createFileRoute("/auth")({
  validateSearch: (s: Record<string, unknown>): AuthSearch => ({
    redirect: typeof s.redirect === "string" ? s.redirect : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Sign in — AI CFO" },
      { name: "description", content: "Sign in or create an AI CFO account to access your autonomous financial workspace." },
      { property: "og:title", content: "Sign in — AI CFO" },
      { property: "og:description", content: "Access your autonomous financial workspace." },
    ],
  }),
  component: AuthPage,
});

function AuthPage() {
  const { login, register, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const search = useSearch({ from: "/auth" }) as AuthSearch;
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState("Finance Head");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isAuthenticated) navigate({ to: (search.redirect as any) || "/" });
  }, [isAuthenticated, navigate, search.redirect]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register({ email, password, full_name: fullName, role });
      }
      toast.success(mode === "login" ? "Welcome back" : "Account created");
      navigate({ to: (search.redirect as any) || "/" });
    } catch (err: any) {
      toast.error(err?.message || "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 flex items-center justify-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Sparkles className="h-4 w-4" />
          </div>
          <div>
            <p className="font-display text-xl leading-none">AI CFO</p>
            <p className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">Financial OS</p>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-8">
          <h1 className="font-display text-3xl">
            {mode === "login" ? "Sign in" : "Create account"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {mode === "login" ? "Access your financial workspace." : "Spin up a new autonomous CFO workspace."}
          </p>

          <form onSubmit={onSubmit} className="mt-6 space-y-4">
            {mode === "register" && (
              <div className="space-y-2">
                <Label htmlFor="fullName">Full name</Label>
                <Input id="fullName" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete={mode === "login" ? "current-password" : "new-password"} />
            </div>
            {mode === "register" && (
              <div className="space-y-2">
                <Label htmlFor="role">Role</Label>
                <Input id="role" value={role} onChange={(e) => setRole(e.target.value)} />
              </div>
            )}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>

          <button
            type="button"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
            className="mt-6 w-full text-center text-xs text-muted-foreground hover:text-foreground transition"
          >
            {mode === "login" ? "No account yet? Register" : "Already have an account? Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}
