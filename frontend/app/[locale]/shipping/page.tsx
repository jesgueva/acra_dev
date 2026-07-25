import { PrivilegeGate } from "@/src/components/auth/PrivilegeGate";
import { ShippingView } from "@/src/components/shipping/ShippingView";
import { PRIVILEGES } from "@/src/lib/privileges";

export default function ShippingPage() {
  return (
    <PrivilegeGate privilege={PRIVILEGES.SHIPPING_VIEW}>
      <ShippingView />
    </PrivilegeGate>
  );
}
