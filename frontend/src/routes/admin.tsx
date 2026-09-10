import { createFileRoute, redirect } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Shield, Users, Building2, Check, X, UserCheck, UserX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { AdminAPI, type AdminUser, type CompanyInfo } from "@/lib/api";

export const Route = createFileRoute("/admin")({
  beforeLoad: ({ context }) => {
    // Redirect if not admin
    const user = (context as any)?.user;
    if (user && user.role !== "admin") {
      throw redirect({ to: "/" });
    }
  },
  head: () => ({
    meta: [
      { title: "Admin Panel — AI CFO" },
      { name: "description", content: "Manage users and company settings." },
    ],
  }),
  component: AdminPanel,
});

function AdminPanel() {
  const { user, isAdmin } = useAuth();
  const queryClient = useQueryClient();
  const [companyName, setCompanyName] = useState("");

  // Fetch company users
  const { data: usersData, isLoading: usersLoading } = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => AdminAPI.listUsers(),
    enabled: isAdmin,
  });

  // Fetch company info
  const { data: companyData, isLoading: companyLoading } = useQuery({
    queryKey: ["admin-company"],
    queryFn: () => AdminAPI.getCompany(),
    enabled: isAdmin,
  });

  // Update user role mutation
  const updateRoleMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: number; role: string }) =>
      AdminAPI.updateUserRole(userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("User role updated");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update role");
    },
  });

  // Update user status mutation
  const updateStatusMutation = useMutation({
    mutationFn: ({ userId, isActive }: { userId: number; isActive: boolean }) =>
      AdminAPI.updateUserStatus(userId, isActive),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      toast.success("User status updated");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update status");
    },
  });

  // Update company mutation
  const updateCompanyMutation = useMutation({
    mutationFn: (name: string) => AdminAPI.updateCompany(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-company"] });
      toast.success("Company settings updated");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update company");
    },
  });

  if (!isAdmin) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <Shield className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
          <h2 className="text-xl font-semibold">Access Denied</h2>
          <p className="text-muted-foreground">You need admin privileges to access this page.</p>
        </div>
      </div>
    );
  }

  const users = usersData?.users || [];
  const company = companyData;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Shield className="h-6 w-6 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Admin Panel</h1>
          <p className="text-sm text-muted-foreground">Manage users and company settings</p>
        </div>
      </div>

      {/* Company Info */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Building2 className="h-5 w-5" />
            Company Information
          </CardTitle>
          <CardDescription>Manage your company settings</CardDescription>
        </CardHeader>
        <CardContent>
          {companyLoading ? (
            <p className="text-muted-foreground">Loading...</p>
          ) : (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label className="text-sm text-muted-foreground">Domain</Label>
                  <p className="font-medium">{company?.domain || "N/A"}</p>
                </div>
                <div>
                  <Label className="text-sm text-muted-foreground">Total Users</Label>
                  <p className="font-medium">{company?.user_count || 0}</p>
                </div>
                <div>
                  <Label className="text-sm text-muted-foreground">Admins</Label>
                  <p className="font-medium">{company?.admin_count || 0}</p>
                </div>
                <div>
                  <Label className="text-sm text-muted-foreground">Created</Label>
                  <p className="font-medium">
                    {company?.created_at ? new Date(company.created_at).toLocaleDateString() : "N/A"}
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <Input
                  placeholder="Company name"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                />
                <Button
                  onClick={() => updateCompanyMutation.mutate(companyName)}
                  disabled={!companyName || updateCompanyMutation.isPending}
                >
                  {updateCompanyMutation.isPending ? "Saving..." : "Save"}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* User Management */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            User Management
          </CardTitle>
          <CardDescription>Manage users in your company</CardDescription>
        </CardHeader>
        <CardContent>
          {usersLoading ? (
            <p className="text-muted-foreground">Loading users...</p>
          ) : (
            <div className="space-y-4">
              {users.length === 0 ? (
                <p className="text-muted-foreground text-center py-4">No users found</p>
              ) : (
                <div className="border rounded-lg">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b bg-muted/50">
                        <th className="text-left p-3 text-sm font-medium">User</th>
                        <th className="text-left p-3 text-sm font-medium">Role</th>
                        <th className="text-left p-3 text-sm font-medium">Status</th>
                        <th className="text-right p-3 text-sm font-medium">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {users.map((u: AdminUser) => (
                        <tr key={u.id} className="border-b last:border-b-0">
                          <td className="p-3">
                            <div>
                              <p className="font-medium">{u.full_name}</p>
                              <p className="text-sm text-muted-foreground">{u.email}</p>
                            </div>
                          </td>
                          <td className="p-3">
                            <Badge variant={u.role === "admin" ? "default" : "secondary"}>
                              {u.role === "admin" ? "Admin" : "User"}
                            </Badge>
                          </td>
                          <td className="p-3">
                            <Badge variant={u.is_active ? "default" : "destructive"}>
                              {u.is_active ? "Active" : "Inactive"}
                            </Badge>
                          </td>
                          <td className="p-3 text-right">
                            <div className="flex gap-1 justify-end">
                              {u.id !== user?.id && (
                                <>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() =>
                                      updateRoleMutation.mutate({
                                        userId: u.id,
                                        role: u.role === "admin" ? "user" : "admin",
                                      })
                                    }
                                    disabled={updateRoleMutation.isPending}
                                  >
                                    {u.role === "admin" ? "Demote" : "Promote"}
                                  </Button>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() =>
                                      updateStatusMutation.mutate({
                                        userId: u.id,
                                        isActive: !u.is_active,
                                      })
                                    }
                                    disabled={updateStatusMutation.isPending}
                                  >
                                    {u.is_active ? (
                                      <UserX className="h-4 w-4" />
                                    ) : (
                                      <UserCheck className="h-4 w-4" />
                                    )}
                                  </Button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
