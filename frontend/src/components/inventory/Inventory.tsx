"use client";

import { useCallback, useMemo, useState } from "react";
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
import {
  DEFAULT_FILTERS,
  filtersToParams,
  FilterState,
  InventoryItem,
  InventoryResponse,
} from "./types";

export function Inventory() {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const roles = user?.roles ?? [];
  const isAdmin = roles.includes(ROLES.ADMIN);

  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [selectedLot, setSelectedLot] = useState<string | null>(null);
  const [adjustItem, setAdjustItem] = useState<InventoryItem | null>(null);

  const { data, isLoading } = useQuery<InventoryResponse>({
    queryKey: ["inventory", filters],
    queryFn: async () => {
      const params = filtersToParams(filters);
      const res = await apiClient.get<InventoryResponse>(
        `/inventory${params.toString() ? `?${params}` : ""}`
      );
      return res.data;
    },
  });

  const items = useMemo(() => data?.items ?? [], [data]);

  const handleRowClick = useCallback(
    (item: InventoryItem) => setSelectedLot(item.lot_batch_number),
    []
  );
  const handleAdjust = useCallback(
    (item: InventoryItem) => setAdjustItem(item),
    []
  );
  const handleAdjustSuccess = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["inventory"] }),
    [queryClient]
  );
  const handleCloseLot = useCallback(() => setSelectedLot(null), []);
  const handleCloseAdjust = useCallback(() => setAdjustItem(null), []);

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
          onRowClick={handleRowClick}
          onAdjust={handleAdjust}
        />
      )}

      <TraceabilityView
        lotBatchNumber={selectedLot}
        onClose={handleCloseLot}
      />

      <AdjustQuantityModal
        item={adjustItem}
        onClose={handleCloseAdjust}
        onSuccess={handleAdjustSuccess}
      />
    </div>
  );
}
