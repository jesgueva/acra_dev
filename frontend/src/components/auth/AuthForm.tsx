"use client";

import React, { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/src/contexts/AuthContext";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function AuthForm() {
  const t = useTranslations("auth");
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuth();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const sessionExpired = searchParams.get("reason") === "session_expired";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login({ username, password });
      router.push("/dashboard");
    } catch (err) {
      const statusErr = err as Error & { status?: number };
      if (statusErr.status === 401) {
        setError(t("invalidCredentials"));
      } else if (statusErr.status === 403) {
        setError(t("accountDeactivated"));
      } else {
        setError(t("loginError"));
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <CardHeader>
        <CardTitle>{t("login")}</CardTitle>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          {sessionExpired && (
            <p
              className="text-sm text-yellow-700 bg-yellow-50 rounded-md px-3 py-2"
              role="status"
            >
              {t("sessionExpired")}
            </p>
          )}

          {error && (
            <p
              className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2"
              role="alert"
            >
              {error}
            </p>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="username">{t("username")}</Label>
            <Input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="password">{t("password")}</Label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>

          <Button type="submit" disabled={loading} className="w-full">
            {loading ? (
              <Loader2 className="animate-spin" aria-label="loading" />
            ) : (
              t("loginButton")
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
