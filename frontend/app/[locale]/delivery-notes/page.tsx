import { PrivilegeGate } from "@/src/components/auth/PrivilegeGate";
import { DeliveryNotesView } from "@/src/components/delivery-notes/DeliveryNotesView";
import { PRIVILEGES } from "@/src/lib/privileges";

export default function DeliveryNotesPage() {
  return (
    // Mirrors the API's require_any_privilege("deliveries.view", "shipping.view").
    <PrivilegeGate
      privilege={[PRIVILEGES.DELIVERIES_VIEW, PRIVILEGES.SHIPPING_VIEW]}
    >
      <DeliveryNotesView />
    </PrivilegeGate>
  );
}
