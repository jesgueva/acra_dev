import { PrivilegeGate } from "@/src/components/auth/PrivilegeGate";
import { Inventory } from "@/src/components/inventory/Inventory";
import { PRIVILEGES } from "@/src/lib/privileges";

export default function InventoryPage() {
  return (
    <PrivilegeGate privilege={PRIVILEGES.INVENTORY_VIEW}>
      <Inventory />
    </PrivilegeGate>
  );
}
