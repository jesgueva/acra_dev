"use client";

import { LogOut } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import AcraLogo from "@/src/components/brand/AcraLogo";
import { useAuth } from "@/src/contexts/AuthContext";

export default function HeaderBar() {
  const t = useTranslations("nav");
  const locale = useLocale();
  const pathname = usePathname();
  const router = useRouter();
  const { user, isAuthenticated, logout } = useAuth();

  if (!isAuthenticated || pathname === `/${locale}/login`) {
    return null;
  }

  async function handleLogout() {
    await logout();
    router.replace(`/${locale}/login`);
  }

  return (
    <header className="sticky top-0 z-40 border-b border-border/60 bg-background/95 backdrop-blur">
      <div className="mx-auto flex min-h-16 w-full max-w-7xl items-center justify-between px-4 sm:px-6">
        <div className="flex items-center gap-3">
          <AcraLogo />
          <div>
            <p className="text-sm font-semibold tracking-[0.18em] text-muted-foreground">
              ACRA MES
            </p>
            <p className="text-base font-semibold text-foreground">Operations Console</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden rounded-2xl border border-border/70 bg-muted/40 px-3 py-2 text-right sm:block">
            <p className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
              Signed in
            </p>
            <p className="text-sm font-medium text-foreground">{user?.full_name}</p>
          </div>

          <Button
            type="button"
            variant="outline"
            onClick={handleLogout}
            aria-label="logout"
            className="rounded-2xl"
          >
            <LogOut />
            {t("logout")}
          </Button>
        </div>
      </div>
    </header>
  );
}
