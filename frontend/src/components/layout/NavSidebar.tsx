"use client";

import React, { useMemo } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { useAuth } from "@/src/contexts/AuthContext";
import { apiClient } from "@/src/lib/api-client";
import { PRIVILEGES } from "@/src/lib/privileges";

interface NavLink {
  href: string;
  label: string;
  privilege: string;
}

export default function NavSidebar() {
  const t = useTranslations("nav");
  const locale = useLocale();
  const pathname = usePathname();
  const { hasPrivilege, logout, user } = useAuth();

  const navLinks = useMemo<NavLink[]>(
    () => [
      { href: `/${locale}/receiving`, label: t("receiving"), privilege: PRIVILEGES.RECEIVING_VIEW },
      { href: `/${locale}/inventory`, label: t("inventory"), privilege: PRIVILEGES.INVENTORY_VIEW },
      { href: `/${locale}/work-orders`, label: t("workOrders"), privilege: PRIVILEGES.WORK_ORDERS_VIEW },
      { href: `/${locale}/users`, label: t("users"), privilege: PRIVILEGES.USERS_MANAGE },
      { href: `/${locale}/audit`, label: t("audit"), privilege: PRIVILEGES.AUDIT_VIEW },
    ],
    [locale, t]
  );

  const visibleLinks = useMemo(
    () => navLinks.filter((link) => hasPrivilege(link.privilege)),
    [navLinks, hasPrivilege]
  );

  async function handleLanguageToggle() {
    if (!user) return;
    const newLang = locale === "en" ? "es" : "en";
    await apiClient
      .patch("/users/me", { preferred_language: newLang })
      .catch(() => {});
    // Hard reload needed to re-hydrate next-intl server messages for the new locale
    window.location.href = pathname.replace(`/${locale}`, `/${newLang}`);
  }

  return (
    <nav aria-label="sidebar" className="flex flex-col h-full bg-white border-r border-gray-200 w-64 p-4">
      <div className="mb-8">
        <span className="text-xl font-bold text-gray-900">ACRA MES</span>
      </div>

      <ul className="flex-1 space-y-1">
        {visibleLinks.map((link) => (
          <li key={link.href}>
            <Link
              href={link.href}
              className={`block px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                pathname.startsWith(link.href)
                  ? "bg-blue-50 text-blue-700"
                  : "text-gray-700 hover:bg-gray-100"
              }`}
            >
              {link.label}
            </Link>
          </li>
        ))}
      </ul>

      <div className="border-t border-gray-200 pt-4 space-y-2">
        {user && (
          <button
            onClick={handleLanguageToggle}
            className="w-full text-left px-3 py-2 rounded-md text-sm text-gray-700 hover:bg-gray-100"
            aria-label="toggle-language"
          >
            {t("language")}: {locale === "en" ? "ES" : "EN"}
          </button>
        )}
        <button
          onClick={logout}
          className="w-full text-left px-3 py-2 rounded-md text-sm text-gray-700 hover:bg-gray-100"
          aria-label="logout"
        >
          {t("logout")}
        </button>
      </div>
    </nav>
  );
}
