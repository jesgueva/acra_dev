import { PrivilegeGate } from "@/src/components/auth/PrivilegeGate";
import { WorkOrders } from "@/src/components/work-orders/WorkOrders";
import { PRIVILEGES } from "@/src/lib/privileges";

export default function WorkOrdersPage() {
  return (
    <PrivilegeGate privilege={PRIVILEGES.WORK_ORDERS_VIEW}>
      <WorkOrders />
    </PrivilegeGate>
  );
}
