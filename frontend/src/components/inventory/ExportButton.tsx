"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Download } from "lucide-react";
import { apiClient } from "@/src/lib/api-client";
import { filtersToParams, FilterState } from "./types";

interface ExportButtonProps {
  filters: FilterState;
}

export function ExportButton({ filters }: ExportButtonProps) {
  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    setError(null);
    try {
      const params = filtersToParams(filters);
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
