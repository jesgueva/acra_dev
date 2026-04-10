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
import { toDisplay } from "@/src/lib/qty";
import { InventoryLot } from "./types";

interface InventoryTrendLineProps {
  items: InventoryLot[];
}

// TODO: Replace with time-series data in v2 when backend supports historical snapshots.
export function InventoryTrendLine({ items }: InventoryTrendLineProps) {
  const chartData = useMemo(
    () =>
      items.slice(0, 10).map((item) => {
        const name = item.product_name ?? `#${item.id}`;
        return {
          name: name.length > 12 ? name.slice(0, 12) + "…" : name,
          quantity: Number(toDisplay(item.quantity_on_hand)),
        };
      }),
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
