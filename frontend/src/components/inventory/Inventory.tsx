"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/src/contexts/AuthContext";
import { ROLES } from "@/src/lib/privileges";
import { apiClient } from "@/src/lib/api-client";
import { InventoryTable } from "./InventoryTable";
import { FilterPanel } from "./FilterPanel";
import { TraceabilityView } from "./TraceabilityView";
import { AdjustQuantityModal } from "./AdjustQuantityModal";
import { ExportButton } from "./ExportButton";
import { InventoryTrendLine } from "./InventoryTrendLine";
import { FilterState, InventoryItem, InventoryResponse } from "./types";

const DEFAULT_FILTERS: FilterState = {
  category: "",
  search: "",
  dateFrom: "",
  dateTo: "",
};

export function Inventory() {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const roles = user?.roles ?? [];
  const isAdmin = roles.includes(ROLES.ADMIN);

  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [selectedLot, setSelectedLot] = useState<string | null>(null);
  const [adjustItem, setAdjustItem] = useState<InventoryItem | null>(null);

  const queryParams = new URLSearchParams();
  if (filters.category) queryParams.set("category", filters.category);
  if (filters.search) queryParams.set("search", filters.search);
  if (filters.dateFrom) queryParams.set("date_from", filters.dateFrom);
  if (filters.dateTo) queryParams.set("date_to", filters.dateTo);

  const { data, isLoading } = useQuery<InventoryResponse>({
    queryKey: ["inventory", filters],
    queryFn: async () => {
      const res = await apiClient.get<InventoryResponse>(
        `/inventory${queryParams.toString() ? `?${queryParams}` : ""}`
      );
      return res.data;
    },
  });

  const items = data?.items ?? [];

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Inventory</h1>
        <ExportButton filters={filters} />
      </div>

      <FilterPanel filters={filters} onChange={setFilters} />

      {isAdmin && items.length > 0 && (
        <InventoryTrendLine items={items} />
      )}

      {isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (
        <InventoryTable
          items={items}
          isAdmin={isAdmin}
          onRowClick={(item) => setSelectedLot(item.lot_batch_number)}
          onAdjust={(item) => setAdjustItem(item)}
        />
      )}

      <TraceabilityView
        lotBatchNumber={selectedLot}
        onClose={() => setSelectedLot(null)}
      />

      <AdjustQuantityModal
        item={adjustItem}
        onClose={() => setAdjustItem(null)}
        onSuccess={() => queryClient.invalidateQueries({ queryKey: ["inventory"] })}
      />
    </div>
  );
}
