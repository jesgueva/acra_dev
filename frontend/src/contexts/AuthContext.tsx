"use client";

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useMemo,
} from "react";
import { setAuthToken, registerLogoutHandler } from "@/src/lib/api-client";

export interface AuthUser {
  user_id: number;
  full_name: string;
  roles: string[];
  preferred_language: string;
  effective_privileges: string[];
}

export interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (credentials: { username: string; password: string }) => Promise<void>;
  logout: () => Promise<void>;
  hasPrivilege: (privilege: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);

  // Restore session from httpOnly cookie via Route Handler
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/auth/me", { signal: controller.signal })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.user && data?.access_token) {
          setUser(data.user);
          setToken(data.access_token);
        }
      })
      .catch((err) => {
        if (err.name !== "AbortError") { /* no active session */ }
      });
    return () => controller.abort();
  }, []);

  // Keep Axios Bearer header in sync with token state
  useEffect(() => {
    setAuthToken(token);
  }, [token]);

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    setUser(null);
    setToken(null);
  }, []);

  // Register the logout handler for the 401 interceptor; clean up on unmount
  useEffect(() => {
    registerLogoutHandler(logout);
    return () => registerLogoutHandler(() => {});
  }, [logout]);

  const login = useCallback(
    async (credentials: { username: string; password: string }) => {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(credentials),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const error = Object.assign(new Error(body.detail ?? "Login failed"), {
          status: res.status,
        });
        throw error;
      }
      const data = await res.json();
      setUser(data.user);
      setToken(data.access_token);
    },
    []
  );

  const hasPrivilege = useCallback(
    (privilege: string) => user?.effective_privileges.includes(privilege) ?? false,
    [user]
  );

  const value = useMemo<AuthContextValue>(
    () => ({ user, token, isAuthenticated: user !== null, login, logout, hasPrivilege }),
    [user, token, login, logout, hasPrivilege]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
