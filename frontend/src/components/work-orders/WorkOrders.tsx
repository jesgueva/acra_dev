"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/src/contexts/AuthContext";
import { apiClient } from "@/src/lib/api-client";
import { ROLES, PRIVILEGES } from "@/src/lib/privileges";
import type { WorkOrder, WorkOrderListResponse } from "./types";
import { WorkOrderList } from "./WorkOrderList";
import { WorkOrderDetail } from "./WorkOrderDetail";
import { CreateWorkOrderForm } from "./CreateWorkOrderForm";

const STATUS_ORDER = [
  "created",
  "materials_allocated",
  "in_production",
  "completed",
  "ready_for_shipment",
] as const;

export function WorkOrders() {
  const { user, hasPrivilege } = useAuth();
  const roles = user?.roles ?? [];
  const isOperator = roles.includes(ROLES.OPERATOR);
  const canCreate = hasPrivilege(PRIVILEGES.WORK_ORDERS_CREATE);

  const [selectedWO, setSelectedWO] = useState<WorkOrder | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const { data, refetch } = useQuery<WorkOrderListResponse>({
    queryKey: ["work-orders", isOperator],
    queryFn: async () => {
      const params = new URLSearchParams({ page_size: "250" });
      if (isOperator) params.set("status", "in_production");
      const res = await apiClient.get<WorkOrderListResponse>(
        `/work-orders?${params}`
      );
      return res.data;
    },
    enabled: hasPrivilege(PRIVILEGES.WORK_ORDERS_VIEW),
  });

  const workOrders = data?.results ?? [];

  // Group work orders by status; operators see only in_production
  const groups = STATUS_ORDER.reduce<Record<string, WorkOrder[]>>(
    (acc, status) => {
      if (isOperator && status !== "in_production") return acc;
      const items = workOrders.filter((wo) => wo.status === status);
      acc[status] = items;
      return acc;
    },
    {}
  );

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Work Orders</h1>
        {canCreate && (
          <Button onClick={() => setShowCreate(true)}>
            <Plus className="mr-2 h-4 w-4" />
            Create Work Order
          </Button>
        )}
      </div>

      <WorkOrderList groups={groups} onSelect={setSelectedWO} />

      {selectedWO && (
        <WorkOrderDetail
          workOrder={selectedWO}
          onClose={() => setSelectedWO(null)}
          onUpdated={() => {
            refetch();
            setSelectedWO(null);
          }}
        />
      )}

      {showCreate && (
        <CreateWorkOrderForm
          open={showCreate}
          onClose={() => setShowCreate(false)}
          onCreated={() => refetch()}
        />
      )}
    </div>
  );
}
