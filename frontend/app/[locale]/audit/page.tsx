import { PrivilegeGate } from "@/src/components/auth/PrivilegeGate";
import { Audit } from "@/src/components/audit/Audit";
import { PRIVILEGES } from "@/src/lib/privileges";

export default function AuditPage() {
  return (
    <PrivilegeGate privilege={PRIVILEGES.AUDIT_VIEW}>
      <Audit />
    </PrivilegeGate>
  );
}
