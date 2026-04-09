"use client";

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
} from "react";

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

  // Restore session from httpOnly cookie via server Route Handler
  useEffect(() => {
    fetch("/api/auth/me")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.user && data?.access_token) {
          setUser(data.user);
          setToken(data.access_token);
        }
      })
      .catch(() => {/* no session */});
  }, []);

  const login = useCallback(
    async (credentials: { username: string; password: string }) => {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(credentials),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail ?? "Login failed");
      }
      const data = await res.json();
      setUser(data.user);
      setToken(data.access_token);
    },
    []
  );

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    setUser(null);
    setToken(null);
  }, []);

  const hasPrivilege = useCallback(
    (privilege: string) => {
      if (!user) return false;
      return user.effective_privileges.includes(privilege);
    },
    [user]
  );

  const value: AuthContextValue = {
    user,
    token,
    isAuthenticated: user !== null,
    login,
    logout,
    hasPrivilege,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
