"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
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

const PAGE_SIZE = 20;

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

  const deliveries = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
    if (status === "confirmed") return "default";
    if (status === "pending") return "secondary";
    return "outline";
  }

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
            {isLoading ? (
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
