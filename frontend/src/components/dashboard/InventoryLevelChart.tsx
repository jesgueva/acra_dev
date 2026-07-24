"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";

export interface InventoryChartItem {
  material_name: string;
  quantity: number;
  threshold: number;
}

interface InventoryLevelChartProps {
  data: InventoryChartItem[];
}

export function InventoryLevelChart({ data }: InventoryLevelChartProps) {
  const top5 = data.slice(0, 5);
  const maxThreshold = top5.reduce((max, d) => Math.max(max, d.threshold), 0);

  return (
    <div>
      <h2 className="mb-2 text-sm font-medium text-muted-foreground">
        Inventory Levels — Top Materials
      </h2>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={top5} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
          <XAxis dataKey="material_name" tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          {maxThreshold > 0 && (
            <ReferenceLine
              y={maxThreshold}
              stroke="var(--destructive)"
              strokeDasharray="4 2"
              label={{ value: "Threshold", position: "insideTopRight", fontSize: 11 }}
            />
          )}
          {/* `var(--primary)`, not `hsl(var(--primary))`: the tokens in globals.css are complete
              oklch() colours, so wrapping them in hsl() produced invalid CSS and the bars fell back
              to near-black — invisible against the dark theme. */}
          <Bar dataKey="quantity" fill="var(--primary)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
