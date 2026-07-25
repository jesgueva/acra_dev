import { PrivilegeGate } from "@/src/components/auth/PrivilegeGate";
import ReceivingView from "@/src/components/receiving/ReceivingView";
import { PRIVILEGES } from "@/src/lib/privileges";

export default function ReceivingPage() {
  return (
    <PrivilegeGate privilege={PRIVILEGES.RECEIVING_VIEW}>
      <ReceivingView />
    </PrivilegeGate>
  );
}
