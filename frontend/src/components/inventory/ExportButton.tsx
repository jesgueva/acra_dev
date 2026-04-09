"use client";

import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";
import { apiClient } from "@/src/lib/api-client";
import { FilterState } from "./types";

interface ExportButtonProps {
  filters: FilterState;
}

export function ExportButton({ filters }: ExportButtonProps) {
  const handleExport = async () => {
    const params = new URLSearchParams();
    if (filters.category) params.set("category", filters.category);
    if (filters.search) params.set("search", filters.search);
    if (filters.dateFrom) params.set("date_from", filters.dateFrom);
    if (filters.dateTo) params.set("date_to", filters.dateTo);

    const url = `/inventory/export${params.toString() ? `?${params}` : ""}`;

    const res = await apiClient.get(url, { responseType: "blob" });
    const blob = new Blob([res.data as BlobPart], { type: "text/csv" });
    const href = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = href;
    link.download = "inventory_export.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(href);
  };

  return (
    <Button variant="outline" size="sm" onClick={handleExport} data-testid="export-button">
      <Download className="mr-2 h-4 w-4" />
      Export CSV
    </Button>
  );
}
