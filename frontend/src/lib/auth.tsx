import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { AuthAPI, getStoredUser, setStoredUser, type StoredUser } from "./api";

interface AuthContextValue {
  user: StoredUser | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: { email: string; password: string; full_name: string; role?: string }) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<StoredUser | null>(() => getStoredUser());

  useEffect(() => {
    const handler = () => setUser(getStoredUser());
    window.addEventListener("aicfo:user-changed", handler);
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener("aicfo:user-changed", handler);
      window.removeEventListener("storage", handler);
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await AuthAPI.login({ email, password });
    setStoredUser(res.user);
    setUser(res.user);
  }, []);

  const register = useCallback(
    async (payload: { email: string; password: string; full_name: string; role?: string }) => {
      const res = await AuthAPI.register(payload);
      // Backend register returns user_id only; fetch full profile.
      const me = await AuthAPI.me(res.user_id);
      setStoredUser(me);
      setUser(me);
    },
    [],
  );

  const logout = useCallback(() => {
    setStoredUser(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isAuthenticated: !!user, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
