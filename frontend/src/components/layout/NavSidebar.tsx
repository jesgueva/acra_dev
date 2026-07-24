"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import {
  Truck,
  Boxes,
  ClipboardList,
  Users,
  ScrollText,
  LogOut,
  Languages,
  Cpu,
  Database,
  PackageCheck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { ThemeToggle } from "@/src/components/layout/ThemeToggle";
import { useAuth } from "@/src/contexts/AuthContext";
import { apiClient } from "@/src/lib/api-client";
import { PRIVILEGES } from "@/src/lib/privileges";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { key: "receiving" as const, path: "receiving", icon: Truck, privilege: PRIVILEGES.RECEIVING_VIEW },
  { key: "inventory" as const, path: "inventory", icon: Boxes, privilege: PRIVILEGES.INVENTORY_VIEW },
  // { key: "workOrders" as const, path: "work-orders", icon: ClipboardList, privilege: PRIVILEGES.RECEIVING_VIEW },
  // { key: "shippingNav" as const, path: "shipping", icon: PackageCheck, privilege: PRIVILEGES.RECEIVING_VIEW },
  { key: "contacts" as const, path: "master-data/contacts", icon: Database, privilege: PRIVILEGES.RECEIVING_VIEW },
  { key: "users" as const, path: "users", icon: Users, privilege: PRIVILEGES.USERS_MANAGE },
  { key: "audit" as const, path: "audit", icon: ScrollText, privilege: PRIVILEGES.AUDIT_VIEW },
];

export default function NavSidebar() {
  const t = useTranslations("nav");
  const locale = useLocale();
  const pathname = usePathname();
  const { hasPrivilege, isAuthenticated, logout, user } = useAuth();

  if (!isAuthenticated || pathname === `/${locale}/login`) {
    return null;
  }

  const visibleItems = NAV_ITEMS.filter((item) => hasPrivilege(item.privilege));

  const initials = user?.full_name
    ? user.full_name.split(" ").map((n) => n[0]).slice(0, 2).join("").toUpperCase()
    : "—";

  const roleLabel = user?.roles?.[0]?.replace(/_/g, " ").toLowerCase() ?? "user";

  async function handleLanguageToggle() {
    if (!user) return;
    const newLang = locale === "en" ? "es" : "en";
    await apiClient.patch("/users/me", { preferred_language: newLang }).catch(() => {});
    window.location.href = pathname.replace(`/${locale}`, `/${newLang}`);
  }

  async function handleLogout() {
    await logout();
    window.location.href = `/${locale}/login`;
  }

  return (
    <aside
      aria-label="sidebar"
      className="fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-border bg-sidebar"
    >
      <div className="flex items-center gap-3 border-b border-border px-5 py-4">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/15">
          <Cpu className="h-5 w-5 text-primary" />
        </div>
        <div className="min-w-0">
          <p className="font-heading text-base font-bold leading-tight text-foreground">
            ACRA MES
          </p>
          <div className="mt-0.5 flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-chart-4" />
            <p className="text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">
              System Active
            </p>
          </div>
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-3 py-4">
        <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground/60">
          Navigation
        </p>
        <ul className="space-y-0.5">
          {visibleItems.map(({ key, path, icon: Icon }) => {
            const href = `/${locale}/${path}`;
            const isActive = pathname.startsWith(href);
            return (
              <li key={key}>
                <Link
                  href={href}
                  className={cn(
                    "group flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-all",
                    isActive
                      ? "bg-primary/12 text-primary"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )}
                >
                  <Icon
                    className={cn(
                      "h-4 w-4 shrink-0 transition-colors",
                      isActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground",
                    )}
                  />
                  <span className="flex-1">{t(key)}</span>
                  {isActive && (
                    <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="px-3 pb-3">
        <Separator className="mb-3" />

        {user && (
          <>
            <div className="mb-2 flex items-center gap-3 rounded-md bg-accent/50 px-3 py-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-primary">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-foreground leading-tight">
                  {user.full_name}
                </p>
                <Badge variant="secondary" className="mt-0.5 h-4 px-1.5 text-[10px] capitalize">
                  {roleLabel}
                </Badge>
              </div>
            </div>
            <Separator className="mb-2" />
          </>
        )}

        <ThemeToggle />

        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start gap-3 text-muted-foreground hover:text-foreground"
          onClick={handleLanguageToggle}
          aria-label="toggle-language"
        >
          <Languages className="h-4 w-4" />
          {t("language")}: {locale === "en" ? "ES" : "EN"}
        </Button>

        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start gap-3 text-muted-foreground hover:text-destructive"
          onClick={handleLogout}
          aria-label="logout"
        >
          <LogOut className="h-4 w-4" />
          {t("logout")}
        </Button>
      </div>
    </aside>
  );
}
