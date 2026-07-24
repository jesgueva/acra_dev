"use client";

import { useQuery } from "@tanstack/react-query";
import {
  type LucideIcon,
  Package,
  Truck,
  ClipboardList,
  Users,
  AlertTriangle,
  ShoppingCart,
} from "lucide-react";

import { useAuth } from "@/src/contexts/AuthContext";
import { apiClient } from "@/src/lib/api-client";
import { ROLES } from "@/src/lib/privileges";
import { SummaryCard } from "./SummaryCard";
import { AlertBanner, type AlertItem } from "./AlertBanner";
import { QuickActionBar } from "./QuickActionBar";
import { InventoryLevelChart, type InventoryChartItem } from "./InventoryLevelChart";

interface SummaryCardDef {
  icon: LucideIcon;
  label: string;
  value: string | number;
}

interface AdminCardCounts {
  alertCount: number;
  deliveryCount: number;
  workOrderCount: number;
  userCount: number;
}

function buildAdminCards({
  alertCount,
  deliveryCount,
  workOrderCount,
  userCount,
}: AdminCardCounts): SummaryCardDef[] {
  return [
    { icon: Truck, label: "Total Deliveries", value: deliveryCount },
    { icon: AlertTriangle, label: "Low Stock Items", value: alertCount },
    { icon: ClipboardList, label: "Active Work Orders", value: workOrderCount },
    { icon: Users, label: "Active Users", value: userCount },
  ];
}

function buildSupervisorCards(workOrderCount: number): SummaryCardDef[] {
  return [
    { icon: ClipboardList, label: "Active Work Orders", value: workOrderCount },
    { icon: Package, label: "Inventory Items", value: "—" },
  ];
}

function buildClerkCards(deliveryCount: number): SummaryCardDef[] {
  return [
    { icon: Truck, label: "Deliveries Today", value: deliveryCount },
    { icon: ShoppingCart, label: "Pending Confirmations", value: "—" },
  ];
}

function buildOperatorCards(workOrderCount: number): SummaryCardDef[] {
  return [
    { icon: ClipboardList, label: "My Active Work Orders", value: workOrderCount },
  ];
}

export function Dashboard() {
  const { user } = useAuth();
  const roles = user?.roles ?? [];

  const isAdmin = roles.includes(ROLES.ADMIN);
  const isSupervisor = roles.includes(ROLES.SUPERVISOR);
  const isClerk = roles.includes(ROLES.CLERK);
  const isOperator = roles.includes(ROLES.OPERATOR);

  const { data: alerts = [] } = useQuery<AlertItem[]>({
    queryKey: ["inventory-alerts"],
    queryFn: async () => {
      // `GET /inventory/alerts` returns `{ alerts: [...] }`, not a bare array. Reading `res.data`
      // handed a plain object to `alerts.filter(...)` below and crashed the whole dashboard with
      // "TypeError: filter is not a function".
      const res = await apiClient.get<{ alerts: AlertItem[] }>("/inventory/alerts");
      return res.data.alerts ?? [];
    },
    // Needs inventory.view, which supervisors hold too — and the chart below is built from it.
    enabled: isAdmin || isSupervisor,
  });

  // Built from the alerts response rather than a second request. The previous query asked
  // `/inventory?category=raw&page_size=5` and read `res.data.items`: `category` is not a filter the
  // endpoint supports, and the response key is `results`, so the chart was silently always empty.
  // The alerts payload is also the only source that carries `threshold`, which the chart needs.
  const inventoryItems: InventoryChartItem[] = alerts.map((alert) => ({
    material_name: alert.product_name,
    quantity: alert.current_quantity,
    threshold: alert.threshold,
  }));

  const { data: deliveryCount = 0 } = useQuery<number>({
    queryKey: ["deliveries-count"],
    queryFn: async () => {
      const res = await apiClient.get<{ total: number }>("/deliveries?page_size=1");
      return res.data.total ?? 0;
    },
    enabled: isAdmin || isClerk,
  });

  const { data: workOrderCount = 0 } = useQuery<number>({
    queryKey: ["work-orders-count"],
    queryFn: async () => {
      const res = await apiClient.get<{ total: number }>("/work-orders?page_size=1");
      return res.data.total ?? 0;
    },
    enabled: isAdmin || isSupervisor || isOperator,
  });

  const { data: userCount = 0 } = useQuery<number>({
    queryKey: ["users-count"],
    queryFn: async () => {
      const res = await apiClient.get<{ total: number }>("/users?page_size=1");
      return res.data.total ?? 0;
    },
    enabled: isAdmin,
  });

  let cards: SummaryCardDef[] = [];
  if (isAdmin) {
    cards = buildAdminCards({
      alertCount: alerts.filter((a) => a.is_triggered).length,
      deliveryCount,
      workOrderCount,
      userCount,
    });
  } else if (isSupervisor) {
    cards = buildSupervisorCards(workOrderCount);
  } else if (isClerk) {
    cards = buildClerkCards(deliveryCount);
  } else if (isOperator) {
    cards = buildOperatorCards(workOrderCount);
  }

  const showChart = isAdmin || isSupervisor;

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>

      {isAdmin && <AlertBanner alerts={alerts} />}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <SummaryCard
            key={card.label}
            icon={card.icon}
            label={card.label}
            value={card.value}
          />
        ))}
      </div>

      {showChart && inventoryItems.length > 0 && (
        <InventoryLevelChart data={inventoryItems} />
      )}

      <QuickActionBar roles={roles} />
    </div>
  );
}
