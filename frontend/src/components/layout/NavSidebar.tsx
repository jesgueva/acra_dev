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
  Factory,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/src/contexts/AuthContext";
import { apiClient } from "@/src/lib/api-client";
import { PRIVILEGES } from "@/src/lib/privileges";

const NAV_ITEMS = [
  { key: "receiving" as const, path: "receiving", icon: Truck, privilege: PRIVILEGES.RECEIVING_VIEW },
  { key: "inventory" as const, path: "inventory", icon: Boxes, privilege: PRIVILEGES.INVENTORY_VIEW },
  { key: "workOrders" as const, path: "work-orders", icon: ClipboardList, privilege: PRIVILEGES.WORK_ORDERS_VIEW },
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
      className="fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-border bg-background"
    >
      {/* Brand */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-5">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10">
          <Factory className="h-5 w-5 text-primary" />
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">
            ACRA MES
          </p>
          <p className="text-sm font-semibold leading-tight text-foreground">Operations</p>
        </div>
      </div>

      {/* Nav links */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="space-y-0.5">
          {visibleItems.map(({ key, path, icon: Icon }) => {
            const href = `/${locale}/${path}`;
            const isActive = pathname.startsWith(href);
            return (
              <li key={key}>
                <Link
                  href={href}
                  className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                    isActive
                      ? "bg-primary/10 text-primary"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  {t(key)}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer */}
      <div className="border-t border-border px-3 py-3">
        {user && (
          <div className="mb-2 px-3 py-2">
            <p className="text-xs text-muted-foreground">Signed in as</p>
            <p className="truncate text-sm font-medium text-foreground">{user.full_name}</p>
          </div>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start gap-3 text-muted-foreground"
          onClick={handleLanguageToggle}
          aria-label="toggle-language"
        >
          <Languages className="h-4 w-4" />
          {t("language")}: {locale === "en" ? "ES" : "EN"}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start gap-3 text-muted-foreground"
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
