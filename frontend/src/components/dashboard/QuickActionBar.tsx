"use client";

import Link from "next/link";
import { useLocale } from "next-intl";
import { Button } from "@/components/ui/button";
import { ROLES } from "@/src/lib/privileges";

interface QuickAction {
  path: string;
  label: string;
}

const ROLE_ACTIONS: Record<string, QuickAction[]> = {
  [ROLES.ADMIN]: [
    { path: "receiving", label: "Receiving" },
    { path: "inventory", label: "Inventory" },
    { path: "work-orders", label: "Work Orders" },
    { path: "users", label: "Users" },
    { path: "audit", label: "Audit Log" },
  ],
  [ROLES.SUPERVISOR]: [
    { path: "inventory", label: "Inventory" },
    { path: "work-orders", label: "Work Orders" },
  ],
  [ROLES.CLERK]: [{ path: "receiving", label: "Receiving" }],
  [ROLES.OPERATOR]: [{ path: "work-orders", label: "Work Orders" }],
};

function getActionsForRoles(roles: string[]): QuickAction[] {
  for (const role of [ROLES.ADMIN, ROLES.SUPERVISOR, ROLES.CLERK, ROLES.OPERATOR]) {
    if (roles.includes(role)) return ROLE_ACTIONS[role] ?? [];
  }
  return [];
}

interface QuickActionBarProps {
  roles: string[];
}

export function QuickActionBar({ roles }: QuickActionBarProps) {
  const locale = useLocale();
  const actions = getActionsForRoles(roles);
  if (actions.length === 0) return null;

  return (
    <nav aria-label="Quick actions" className="flex flex-wrap gap-2">
      {actions.map((action) => (
        <Button key={action.path} variant="outline" asChild>
          <Link href={`/${locale}/${action.path}`}>{action.label}</Link>
        </Button>
      ))}
    </nav>
  );
}
