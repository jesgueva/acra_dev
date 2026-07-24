"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { Menu, LogOut, Languages, Cpu } from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Badge } from "@/components/ui/badge";
import { ThemeToggle } from "@/src/components/layout/ThemeToggle";
import { useAuth } from "@/src/contexts/AuthContext";
import { apiClient } from "@/src/lib/api-client";
import { NAV_ITEMS } from "@/src/components/layout/navItems";
import { cn } from "@/lib/utils";

/**
 * Navigation below the `md` breakpoint (NFR-010).
 *
 * `NavSidebar` is a fixed 256px column, which is two thirds of a 390px phone — so under `md` it is
 * hidden and this takes over: a slim top bar plus a drawer holding the same links.
 *
 * The links come from the shared `NAV_ITEMS` and are filtered by the same `hasPrivilege` check the
 * sidebar uses. Duplicating either would risk the drawer quietly exposing a module the sidebar
 * hides.
 */
export default function MobileNav() {
  const t = useTranslations("nav");
  const locale = useLocale();
  const pathname = usePathname();
  const { hasPrivilege, isAuthenticated, logout, user } = useAuth();
  const [open, setOpen] = useState(false);

  if (!isAuthenticated || pathname === `/${locale}/login`) {
    return null;
  }

  const visibleItems = NAV_ITEMS.filter((item) => hasPrivilege(item.privilege));
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
    <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-border bg-sidebar px-4 py-3 md:hidden">
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label="open navigation"
            data-testid="mobile-nav-trigger"
          >
            <Menu className="h-5 w-5" />
          </Button>
        </SheetTrigger>

        <SheetContent side="left" className="w-72 p-0" data-testid="mobile-nav">
          <SheetHeader className="border-b border-border px-5 py-4">
            <SheetTitle className="flex items-center gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/15">
                <Cpu className="h-5 w-5 text-primary" />
              </span>
              <span className="font-heading text-base font-bold">ACRA MES</span>
            </SheetTitle>
          </SheetHeader>

          <nav className="flex-1 overflow-y-auto px-3 py-4">
            <ul className="space-y-0.5">
              {visibleItems.map(({ key, path, icon: Icon }) => {
                const href = `/${locale}/${path}`;
                const isActive = pathname.startsWith(href);
                return (
                  <li key={key}>
                    <Link
                      href={href}
                      // Dismiss on the click itself rather than in an effect watching `pathname`:
                      // the drawer must not stay open over the page it just navigated to.
                      onClick={() => setOpen(false)}
                      className={cn(
                        "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-all",
                        isActive
                          ? "bg-primary/12 text-primary"
                          : "text-muted-foreground hover:bg-accent hover:text-foreground",
                      )}
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      <span className="flex-1">{t(key)}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          <div className="px-3 pb-4">
            <Separator className="mb-3" />

            {user && (
              <div className="mb-2 px-3">
                <p className="truncate text-sm font-medium leading-tight">{user.full_name}</p>
                <Badge variant="secondary" className="mt-0.5 h-4 px-1.5 text-[10px] capitalize">
                  {roleLabel}
                </Badge>
              </div>
            )}

            <ThemeToggle />

            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start gap-3 text-muted-foreground"
              onClick={handleLanguageToggle}
              aria-label="toggle-language-mobile"
            >
              <Languages className="h-4 w-4" />
              {t("language")}: {locale === "en" ? "ES" : "EN"}
            </Button>

            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start gap-3 text-muted-foreground hover:text-destructive"
              onClick={handleLogout}
              aria-label="logout-mobile"
            >
              <LogOut className="h-4 w-4" />
              {t("logout")}
            </Button>
          </div>
        </SheetContent>
      </Sheet>

      <span className="font-heading text-sm font-bold">ACRA MES</span>
    </header>
  );
}
