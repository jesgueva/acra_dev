"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InventoryItem } from "./types";

interface InventoryTrendLineProps {
  items: InventoryItem[];
}

// TODO: Replace with time-series data in v2 when backend supports historical snapshots.
export function InventoryTrendLine({ items }: InventoryTrendLineProps) {
  const chartData = useMemo(
    () =>
      items.slice(0, 10).map((item) => ({
        name:
          item.material_name.length > 12
            ? item.material_name.slice(0, 12) + "…"
            : item.material_name,
        quantity: item.quantity,
      })),
    [items]
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>Inventory Snapshot</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} data-testid="inventory-trend-chart">
            <XAxis dataKey="name" tick={{ fontSize: 12 }} />
            <YAxis />
            <Tooltip />
            <ReferenceLine y={0} stroke="#e5e7eb" />
            <Bar dataKey="quantity" fill="#3b82f6" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
