import type { ReactNode } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useEffect } from "react";
import {
  LayoutDashboard,
  MessagesSquare,
  Database,
  FileText,
  TrendingUp,
  ShieldAlert,
  Plug,
  Settings2,
  Sparkles,
  LogOut,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { useAuth } from "@/lib/auth";
import { AuthAPI } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";

const nav = [
  { section: "Intelligence", items: [
    { title: "Dashboard", url: "/", icon: LayoutDashboard },
    { title: "AI Chat", url: "/chat", icon: MessagesSquare },
    { title: "Forecasts", url: "/forecasts", icon: TrendingUp },
    { title: "Anomalies", url: "/anomalies", icon: ShieldAlert },
  ]},
  { section: "Operations", items: [
    { title: "Data Sources", url: "/data-sources", icon: Database },
    { title: "Reports", url: "/reports", icon: FileText },
    { title: "Integrations", url: "/integrations", icon: Plug },
  ]},
  { section: "Configuration", items: [
    { title: "AI Settings", url: "/settings", icon: Settings2 },
  ]},
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (r) => r.location.pathname });
  const { user, isAuthenticated, logout } = useAuth();
  const navigate = useNavigate();

  // Auth-gate every route except /auth.
  const onAuthPage = pathname.startsWith("/auth");
  useEffect(() => {
    if (!onAuthPage && !isAuthenticated) {
      navigate({ to: "/auth", search: { redirect: pathname } });
    }
  }, [onAuthPage, isAuthenticated, navigate, pathname]);

  if (onAuthPage) return <>{children}</>;
  if (!isAuthenticated) return null;

  const initials =
    (user?.full_name || user?.email || "U")
      .split(/\s+/)
      .map((s) => s[0])
      .slice(0, 2)
      .join("")
      .toUpperCase();

  const { data: googleStatus, isLoading: googleLoading } = useQuery({
    queryKey: ["google-status"],
    queryFn: () => AuthAPI.googleStatus(),
    refetchOnWindowFocus: true,
  });

  const googleConnected = !!googleStatus?.authenticated;

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full bg-background">
        <Sidebar collapsible="icon" className="border-r">
          <SidebarHeader className="border-b border-sidebar-border">
            <div className="flex items-center gap-2 px-2 py-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                <Sparkles className="h-4 w-4" />
              </div>
              <div className="flex flex-col leading-tight group-data-[collapsible=icon]:hidden">
                <span className="font-display text-base">AI CFO</span>
                <span className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
                  Financial OS
                </span>
              </div>
            </div>
          </SidebarHeader>

          <SidebarContent>
            {nav.map((group) => (
              <SidebarGroup key={group.section}>
                <SidebarGroupLabel className="text-[10px] uppercase tracking-[0.18em]">
                  {group.section}
                </SidebarGroupLabel>
                <SidebarGroupContent>
                  <SidebarMenu>
                    {group.items.map((item) => {
                      const active = pathname === item.url;
                      return (
                        <SidebarMenuItem key={item.url}>
                          <SidebarMenuButton asChild isActive={active} tooltip={item.title}>
                            <Link to={item.url}>
                              <item.icon className="h-4 w-4" />
                              <span>{item.title}</span>
                            </Link>
                          </SidebarMenuButton>
                        </SidebarMenuItem>
                      );
                    })}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            ))}
          </SidebarContent>

          <SidebarFooter className="border-t border-sidebar-border">
            <div className="flex items-center gap-2 px-2 py-2 group-data-[collapsible=icon]:hidden">
              <div className="h-8 w-8 rounded-full bg-accent/15 flex items-center justify-center text-xs font-medium text-accent">
                {initials}
              </div>
              <div className="flex flex-col leading-tight min-w-0 flex-1">
                <span className="text-sm font-medium truncate">{user?.full_name || user?.email}</span>
                <span className="text-[11px] text-muted-foreground truncate">{user?.role || "Member"}</span>
              </div>
              <button
                type="button"
                onClick={logout}
                title="Sign out"
                className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground transition"
              >
                <LogOut className="h-3.5 w-3.5" />
              </button>
            </div>
          </SidebarFooter>
        </Sidebar>

        <div className="flex flex-1 flex-col min-w-0">
          <header className="flex h-14 items-center justify-between border-b border-border bg-background/80 px-4 backdrop-blur sticky top-0 z-10">
            <div className="flex items-center gap-3">
              <SidebarTrigger />
              <div className="hidden md:flex items-center gap-2 text-xs text-muted-foreground">
                <span className="h-1.5 w-1.5 rounded-full bg-success animate-pulse" />
                All agents nominal
                <span className="text-border">·</span>
                <span>User ID: <span className="text-foreground num">{user?.id}</span></span>
              </div>
            </div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              {!googleLoading && (
                <Link
                  to="/integrations"
                  className={`hidden items-center gap-1.5 rounded-full border px-2.5 py-1 sm:inline-flex ${
                    googleConnected
                      ? "border-success/40 bg-success/5 text-success"
                      : "border-warning/40 bg-warning/5 text-warning"
                  }`}
                >
                  <span className={`h-1.5 w-1.5 rounded-full ${googleConnected ? "bg-success" : "bg-warning"}`} />
                  {googleConnected ? "Google linked" : "Google not linked"}
                </Link>
              )}
              <span className="hidden sm:inline">{user?.email}</span>
              <Button variant="ghost" size="sm" onClick={logout} className="h-8 gap-1.5">
                <LogOut className="h-3.5 w-3.5" /> Sign out
              </Button>
            </div>
          </header>
          <main className="flex-1 min-w-0">{children}</main>
        </div>
      </div>
    </SidebarProvider>
  );
}
