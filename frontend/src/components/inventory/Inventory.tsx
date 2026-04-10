"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/src/contexts/AuthContext";
import { ROLES } from "@/src/lib/privileges";
import { apiClient } from "@/src/lib/api-client";
import { InventoryTable } from "./InventoryTable";
import { FilterPanel } from "./FilterPanel";
import { InventoryDetailsModal } from "./InventoryDetailsModal";
import { AdjustQuantityModal } from "./AdjustQuantityModal";
import { LocationEditModal } from "./LocationEditModal";
import { SplitLotModal } from "./SplitLotModal";
import { TransactionLogModal } from "./TransactionLogModal";
import { ExportButton } from "./ExportButton";
import { InventoryTrendLine } from "./InventoryTrendLine";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  DEFAULT_FILTERS,
  filtersToParams,
  FilterState,
  InventoryLot,
  InventoryListResponse,
} from "./types";

const PAGE_SIZE = 50;

export function Inventory() {
  const t = useTranslations("inventory");
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const roles = user?.roles ?? [];
  const isAdmin = roles.includes(ROLES.ADMIN);

  const [filters, setFilters] = useState<FilterState>(DEFAULT_FILTERS);
  const [page, setPage] = useState(1);
  const [selectedItem, setSelectedItem] = useState<InventoryLot | null>(null);
  const [adjustItem, setAdjustItem] = useState<InventoryLot | null>(null);
  const [locationItem, setLocationItem] = useState<InventoryLot | null>(null);
  const [splitItem, setSplitItem] = useState<InventoryLot | null>(null);
  const [logLotId, setLogLotId] = useState<number | null>(null);

  const handleFiltersChange = useCallback((next: FilterState) => {
    setFilters(next);
    setPage(1);
  }, []);

  const { data, isLoading } = useQuery<InventoryListResponse>({
    queryKey: ["inventory", filters, page],
    queryFn: async () => {
      const params = filtersToParams(filters, page, PAGE_SIZE);
      const res = await apiClient.get<InventoryListResponse>(
        `/inventory${params.toString() ? `?${params}` : ""}`
      );
      return res.data;
    },
  });

  const items = useMemo(() => data?.results ?? [], [data]);
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const invalidate = useCallback(
    () => queryClient.invalidateQueries({ queryKey: ["inventory"] }),
    [queryClient]
  );

  const handleRowClick = useCallback((item: InventoryLot) => {
    setSelectedItem(item);
  }, []);

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{t("title")}</h1>
        <ExportButton items={items} />
      </div>

      <FilterPanel filters={filters} onChange={handleFiltersChange} />

      {isAdmin && items.length > 0 && (
        <InventoryTrendLine items={items} />
      )}

      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-3/4" />
        </div>
      ) : (
        <InventoryTable
          items={items}
          isAdmin={isAdmin}
          onRowClick={handleRowClick}
          onAdjust={setAdjustItem}
          onEditLocation={setLocationItem}
          onSplit={setSplitItem}
          onViewLog={(item) => setLogLotId(item.id)}
        />
      )}

      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {t("resultCount", { count: total })}
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || isLoading}
            onClick={() => setPage((p) => p - 1)}
          >
            {t("previous")}
          </Button>
          <span className="text-sm">
            {page} / {totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages || isLoading}
            onClick={() => setPage((p) => p + 1)}
          >
            {t("next")}
          </Button>
        </div>
      </div>

      <InventoryDetailsModal
        item={selectedItem}
        onClose={() => setSelectedItem(null)}
      />

      <AdjustQuantityModal
        item={adjustItem}
        onClose={() => setAdjustItem(null)}
        onSuccess={invalidate}
      />

      <LocationEditModal
        lot={locationItem}
        onClose={() => setLocationItem(null)}
        onSuccess={invalidate}
      />

      <SplitLotModal
        lot={splitItem}
        onClose={() => setSplitItem(null)}
        onSuccess={invalidate}
      />

      <TransactionLogModal
        lotId={logLotId}
        onClose={() => setLogLotId(null)}
      />
    </div>
  );
}
