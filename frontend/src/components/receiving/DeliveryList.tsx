"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DataTable } from "@/src/components/layout/DataTable";
import { apiClient } from "@/src/lib/api-client";
import { toDisplay } from "@/src/lib/qty";

const PAGE_SIZE = 20;

interface DeliveryItem {
  id: number;
  product_id: number | null;
  product_name: string | null;
  description: string | null;
  quantity: number;
  pallets: number | null;
  units_per_pallet: number | null;
  leftover: number | null;
  inventory_lot_id: number | null;
}

interface DeliveryDetail {
  id: number;
  contact_id: number | null;
  contact_name: string | null;
  carrier_id: number | null;
  carrier_name: string | null;
  bol_reference: string;
  delivery_date: string;
  notes: string | null;
  created_by: number;
  created_by_name: string | null;
  created_at: string;
  items: DeliveryItem[];
}

interface PaginatedDeliveries {
  results: DeliveryDetail[];
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
  const [selectedDelivery, setSelectedDelivery] = useState<DeliveryDetail | null>(null);

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
          <TableRow
            key={d.id}
            className="cursor-pointer"
            onClick={() => setSelectedDelivery(d)}
          >
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

      <Dialog
        open={selectedDelivery !== null}
        onOpenChange={(open) => {
          if (!open) setSelectedDelivery(null);
        }}
      >
        <DialogContent className="sm:max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="font-mono text-base">
              {selectedDelivery?.bol_reference}
            </DialogTitle>
            <DialogDescription>{t("deliveryDetails")}</DialogDescription>
          </DialogHeader>
          {selectedDelivery && (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-muted-foreground">{t("supplier")}</p>
                  <p className="font-medium">{selectedDelivery.contact_name ?? "—"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("carrier")}</p>
                  <p className="font-medium">{selectedDelivery.carrier_name ?? "—"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("deliveryDate")}</p>
                  <p className="font-medium">{selectedDelivery.delivery_date}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("recordedBy")}</p>
                  <p className="font-medium">
                    {selectedDelivery.created_by_name ??
                      `${t("userIdFallback")} ${selectedDelivery.created_by}`}
                  </p>
                </div>
                <div className="col-span-2">
                  <p className="text-muted-foreground">{t("recordedAt")}</p>
                  <p className="font-medium">
                    {new Date(selectedDelivery.created_at).toLocaleString()}
                  </p>
                </div>
              </div>
              {selectedDelivery.notes ? (
                <div>
                  <p className="text-muted-foreground">{t("notes")}</p>
                  <p className="whitespace-pre-wrap">{selectedDelivery.notes}</p>
                </div>
              ) : null}
              <Separator />
              {selectedDelivery.items.length === 0 ? (
                <p className="text-muted-foreground text-center py-4">{t("noLineItems")}</p>
              ) : (
                <div className="rounded-md border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("product")}</TableHead>
                        <TableHead>{t("description")}</TableHead>
                        <TableHead className="text-right">{t("quantity")}</TableHead>
                        <TableHead className="text-right">{t("pallets")}</TableHead>
                        <TableHead className="text-right">{t("unitsPerPallet")}</TableHead>
                        <TableHead className="text-right">{t("leftover")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {selectedDelivery.items.map((item) => (
                        <TableRow key={item.id}>
                          <TableCell>{item.product_name ?? "—"}</TableCell>
                          <TableCell className="max-w-48 truncate" title={item.description ?? undefined}>
                            {item.description ?? "—"}
                          </TableCell>
                          <TableCell className="text-right font-medium tabular-nums">
                            {toDisplay(item.quantity)}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {item.pallets ?? "—"}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {item.units_per_pallet ?? "—"}
                          </TableCell>
                          <TableCell className="text-right tabular-nums">
                            {item.leftover != null ? toDisplay(item.leftover) : "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelectedDelivery(null)}>
              {tc("cancel")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
