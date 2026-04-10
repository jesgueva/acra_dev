"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TableCell, TableRow } from "@/components/ui/table";
import { DataTable } from "@/src/components/layout/DataTable";
import { apiClient } from "@/src/lib/api-client";

const PAGE_SIZE = 20;

interface Delivery {
  id: number;
  contact_id: number | null;
  contact_name: string | null;
  carrier_id: number | null;
  carrier_name: string | null;
  bol_reference: string;
  delivery_date: string;
  notes?: string | null;
}

interface PaginatedDeliveries {
  results: Delivery[];
  total: number;
  page: number;
  page_size: number;
}

interface DeliveryListProps {
  /** Increment to trigger a refetch */
  refetch: number;
}

export default function DeliveryList({ refetch }: DeliveryListProps) {
  const t = useTranslations("receiving");

  const [page, setPage] = useState(1);
  const [supplierFilter, setSupplierFilter] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["deliveries", page, supplierFilter, refetch],
    queryFn: async () => {
      const params: Record<string, string | number> = { page, page_size: PAGE_SIZE };
      if (supplierFilter) params.supplier = supplierFilter;
      const { data } = await apiClient.get<PaginatedDeliveries>("/deliveries", { params });
      return data;
    },
  });

  const deliveries = data?.results ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const columns = [t("supplier"), t("carrier"), t("bolNumber"), t("deliveryDate")];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Input
          placeholder={t("filterBySupplier")}
          value={supplierFilter}
          onChange={(e) => {
            setSupplierFilter(e.target.value);
            setPage(1);
          }}
          className="max-w-xs"
        />
      </div>

      <DataTable
        columns={columns}
        loading={isLoading}
        isEmpty={!isLoading && deliveries.length === 0}
        emptyMessage={t("noDeliveries")}
      >
        {deliveries.map((d) => (
          <TableRow key={d.id}>
            <TableCell>{d.contact_name ?? "—"}</TableCell>
            <TableCell>
              <Badge variant="outline">{d.carrier_name ?? "—"}</Badge>
            </TableCell>
            <TableCell className="font-mono text-xs">{d.bol_reference}</TableCell>
            <TableCell>{d.delivery_date}</TableCell>
          </TableRow>
        ))}
      </DataTable>

      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {total} {total === 1 ? "result" : "results"}
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
    </div>
  );
}
