"use client";

import { useTranslations } from "next-intl";
import { ShieldAlert } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { useAuth } from "@/src/contexts/AuthContext";

interface PrivilegeGateProps {
  /** Privilege the viewer must hold, e.g. PRIVILEGES.USERS_MANAGE */
  privilege: string;
  children: React.ReactNode;
}

/**
 * Page-level authorization.
 *
 * `AuthGate` only establishes *who* the viewer is; it does not check what they
 * may do. Without this, a user who lacks the privilege could reach a module by
 * typing its URL even though `NavSidebar` hides the link.
 */
export function PrivilegeGate({ privilege, children }: PrivilegeGateProps) {
  const t = useTranslations("common");
  const { authResolved, hasPrivilege } = useAuth();

  // Wait for the session to resolve so we don't flash the denial state.
  if (!authResolved) return null;

  if (!hasPrivilege(privilege)) {
    return (
      <div className="p-6">
        <Alert variant="destructive" data-testid="privilege-denied">
          <ShieldAlert className="h-4 w-4" />
          <AlertDescription>{t("accessDenied")}</AlertDescription>
        </Alert>
      </div>
    );
  }

  return <>{children}</>;
}
