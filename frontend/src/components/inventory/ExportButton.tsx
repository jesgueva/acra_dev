"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";
import { toDisplay } from "@/src/lib/qty";
import { InventoryLot } from "./types";

interface ExportButtonProps {
  items: InventoryLot[];
}

function escapeCsv(value: string | number | boolean | null | undefined) {
  const normalized = String(value ?? "").replaceAll('"', '""');
  return `"${normalized}"`;
}

export function ExportButton({ items }: ExportButtonProps) {
  const t = useTranslations("inventory");
  const [error, setError] = useState<string | null>(null);

  const handleExport = () => {
    setError(null);
    try {
      const header = [
        "product_name",
        "lot_number",
        "status",
        "quantity_on_hand",
        "storage_location",
        "is_triggered",
      ];
      const rows = items.map((item) =>
        [
          item.product_name,
          item.lot_number,
          item.status,
          toDisplay(item.quantity_on_hand),
          item.storage_location,
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
      setError(t("exportFailed"));
    }
  };

  return (
    <div className="flex flex-col items-end gap-1">
      <Button variant="outline" size="sm" onClick={handleExport} data-testid="export-button">
        <Download className="mr-2 h-4 w-4" />
        {t("exportCsv")}
      </Button>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}
