"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiClient } from "@/src/lib/api-client";

interface Delivery {
  delivery_id: number;
  supplier: string;
  bol_number: string;
  delivery_date: string;
  status: string;
}

interface PaginatedDeliveries {
  items: Delivery[];
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
  const tc = useTranslations("common");

  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [supplierFilter, setSupplierFilter] = useState("");
  const [loading, setLoading] = useState(false);

  const fetchDeliveries = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | number> = { page, page_size: pageSize };
      if (supplierFilter) params.supplier = supplierFilter;
      const { data } = await apiClient.get<PaginatedDeliveries>("/deliveries", { params });
      setDeliveries(data.items);
      setTotal(data.total);
    } catch {
      // silently ignore — upstream interceptor handles auth errors
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, supplierFilter]);

  useEffect(() => {
    fetchDeliveries();
  }, [fetchDeliveries, refetch]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
    if (status === "confirmed") return "default";
    if (status === "pending") return "secondary";
    return "outline";
  }

  return (
    <div className="space-y-4">
      {/* Filter */}
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

      {/* Table */}
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("supplier")}</TableHead>
              <TableHead>{t("bolNumber")}</TableHead>
              <TableHead>{t("deliveryDate")}</TableHead>
              <TableHead>{t("status")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center py-8">
                  {tc("loading")}
                </TableCell>
              </TableRow>
            ) : deliveries.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                  {t("noDeliveries")}
                </TableCell>
              </TableRow>
            ) : (
              deliveries.map((d) => (
                <TableRow key={d.delivery_id}>
                  <TableCell>{d.supplier}</TableCell>
                  <TableCell>{d.bol_number}</TableCell>
                  <TableCell>{new Date(d.delivery_date).toLocaleDateString()}</TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(d.status)}>{d.status}</Badge>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {total} {total === 1 ? "result" : "results"}
        </p>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || loading}
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
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            {t("next")}
          </Button>
        </div>
      </div>
    </div>
  );
}
