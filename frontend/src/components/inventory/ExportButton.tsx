"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";
import { InventoryItem } from "./types";

interface ExportButtonProps {
  items: InventoryItem[];
}

function escapeCsv(value: string | number | boolean) {
  const normalized = String(value).replaceAll('"', '""');
  return `"${normalized}"`;
}

export function ExportButton({ items }: ExportButtonProps) {
  const [error, setError] = useState<string | null>(null);

  const handleExport = () => {
    setError(null);
    try {
      const header = [
        "material_type",
        "category",
        "lot_batch_number",
        "quantity_on_hand",
        "storage_location",
        "last_updated",
        "is_triggered",
      ];
      const rows = items.map((item) =>
        [
          item.material_type,
          item.category,
          item.lot_batch_number,
          item.quantity_on_hand,
          item.storage_location,
          item.last_updated,
          item.is_triggered,
        ]
          .map(escapeCsv)
          .join(",")
      );
      const csv = [header.join(","), ...rows].join("\n");
      const href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      const link = document.createElement("a");
      link.href = href;
      link.download = "inventory_export.csv";
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(href);
    } catch {
      setError("Export failed. Please try again.");
    }
  };

  return (
    <div className="flex flex-col items-end gap-1">
      <Button variant="outline" size="sm" onClick={handleExport} data-testid="export-button">
        <Download className="mr-2 h-4 w-4" />
        Export CSV
      </Button>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
