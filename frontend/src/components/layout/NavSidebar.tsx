"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations, useLocale } from "next-intl";
import { useAuth } from "@/src/contexts/AuthContext";

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

  const navLinks: NavLink[] = [
    { href: `/${locale}/receiving`, label: t("receiving"), privilege: "receiving.view" },
    { href: `/${locale}/inventory`, label: t("inventory"), privilege: "inventory.view" },
    { href: `/${locale}/work-orders`, label: t("workOrders"), privilege: "work_orders.view" },
    { href: `/${locale}/users`, label: t("users"), privilege: "users.manage" },
    { href: `/${locale}/audit`, label: t("audit"), privilege: "audit.view" },
  ];

  const visibleLinks = navLinks.filter((link) => hasPrivilege(link.privilege));

  async function handleLanguageToggle() {
    if (!user) return;
    const newLang = locale === "en" ? "es" : "en";
    await fetch("/api/v1/users/me", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ preferred_language: newLang }),
    }).catch(() => {});
    // Redirect to same path with new locale
    const newPath = pathname.replace(`/${locale}`, `/${newLang}`);
    window.location.href = newPath;
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
          onClick={() => logout()}
          className="w-full text-left px-3 py-2 rounded-md text-sm text-gray-700 hover:bg-gray-100"
          aria-label="logout"
        >
          {t("logout")}
        </button>
      </div>
    </nav>
  );
}
