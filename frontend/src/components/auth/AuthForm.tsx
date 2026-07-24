"use client";

import { type FormEvent, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/src/contexts/AuthContext";
import { SESSION_EXPIRED_REASON } from "@/src/lib/auth-constants";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function AuthForm() {
  const t = useTranslations("auth");
  const locale = useLocale();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuth();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const sessionExpired = searchParams.get("reason") === SESSION_EXPIRED_REASON;

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login({ username, password });
      // Dashboard, not /receiving: it is the one module every role can see (its panels are chosen
      // by role), whereas production_supervisor and machine_operator hold no `receiving.view` and
      // would land on an access-denied page immediately after a successful login.
      router.push(`/${locale}/dashboard`);
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
    <div className="relative overflow-hidden rounded-xl border border-border bg-card p-6 shadow-lg shadow-black/20">
      <div className="absolute left-0 right-0 top-0 h-px bg-linear-to-r from-transparent via-primary/60 to-transparent" />

      <form onSubmit={handleSubmit} className="space-y-5">
        {sessionExpired && (
          <Alert role="status" className="border-primary/30 bg-primary/8 text-primary [&>svg]:text-primary">
            <AlertDescription>{t("sessionExpired")}</AlertDescription>
          </Alert>
        )}

        {error && (
          <Alert variant="destructive" data-testid="login-error">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-1.5">
          <Label
            htmlFor="username"
            className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
          >
            {t("username")}
          </Label>
          <Input
            id="username"
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            className="bg-input/60 focus-visible:ring-primary/50"
          />
        </div>

        <div className="space-y-1.5">
          <Label
            htmlFor="password"
            className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
          >
            {t("password")}
          </Label>
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
            className="bg-input/60 focus-visible:ring-primary/50"
          />
        </div>

        <Button
          type="submit"
          disabled={loading}
          className="w-full bg-primary font-semibold text-primary-foreground hover:bg-primary/90"
        >
          {loading ? (
            <Loader2 className="animate-spin" aria-label="loading" />
          ) : (
            t("loginButton")
          )}
        </Button>
      </form>
    </div>
  );
}
