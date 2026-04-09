import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ROLES } from "@/src/lib/privileges";

interface QuickAction {
  href: string;
  label: string;
}

const ROLE_ACTIONS: Record<string, QuickAction[]> = {
  [ROLES.ADMIN]: [
    { href: "/receiving", label: "Receiving" },
    { href: "/inventory", label: "Inventory" },
    { href: "/work-orders", label: "Work Orders" },
    { href: "/users", label: "Users" },
    { href: "/audit", label: "Audit Log" },
  ],
  [ROLES.SUPERVISOR]: [
    { href: "/inventory", label: "Inventory" },
    { href: "/work-orders", label: "Work Orders" },
  ],
  [ROLES.CLERK]: [{ href: "/receiving", label: "Receiving" }],
  [ROLES.OPERATOR]: [{ href: "/work-orders", label: "Work Orders" }],
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
  const actions = getActionsForRoles(roles);
  if (actions.length === 0) return null;

  return (
    <nav aria-label="Quick actions" className="flex flex-wrap gap-2">
      {actions.map((action) => (
        <Button key={action.href} variant="outline" asChild>
          <Link href={action.href}>{action.label}</Link>
        </Button>
      ))}
    </nav>
  );
}
