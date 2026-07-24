"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { apiClient } from "@/src/lib/api-client";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { FileText } from "lucide-react";

interface DeliveryNote {
  id: number;
  type: string;
  source: string | null;
  partner_id: number | null;
  partner_name: string | null;
  document_number: string;
  document_date: string;
  uploaded: boolean;
  notes: string | null;
  created_by: number;
  created_at: string;
}

interface DeliveryNoteListResponse {
  total: number;
  page: number;
  page_size: number;
  results: DeliveryNote[];
}

/** §4.1/§4.3 — the four document kinds. */
const NOTE_TYPES = ["inbound", "transfer", "direct_customer", "internal"] as const;

const TYPE_VARIANTS: Record<string, "default" | "secondary" | "outline"> = {
  inbound: "default",
  transfer: "secondary",
  direct_customer: "outline",
  internal: "outline",
};

const ALL = "all";

export function DeliveryNotesView() {
  const t = useTranslations("deliveryNotes");
  const tc = useTranslations("common");

  const [page, setPage] = useState(1);
  const [typeFilter, setTypeFilter] = useState<string>(ALL);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const { data, isLoading, isError } = useQuery<DeliveryNoteListResponse>({
    queryKey: ["delivery-notes", page, typeFilter, dateFrom, dateTo],
    queryFn: () =>
      apiClient
        .get("/delivery-notes", {
          params: {
            page,
            page_size: 20,
            ...(typeFilter !== ALL ? { type: typeFilter } : {}),
            ...(dateFrom ? { date_from: dateFrom } : {}),
            ...(dateTo ? { date_to: dateTo } : {}),
          },
        })
        .then((r) => r.data),
  });

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;
  const hasFilters = typeFilter !== ALL || dateFrom !== "" || dateTo !== "";

  /** Reset to page 1 whenever a filter changes, so results are never stranded. */
  function applyFilter(fn: () => void) {
    fn();
    setPage(1);
  }

  function clearFilters() {
    applyFilter(() => {
      setTypeFilter(ALL);
      setDateFrom("");
      setDateTo("");
    });
  }

  return (
    <div className="space-y-6 p-6">
      <PageHeader title={t("title")} description={t("subtitle")} />

      <div className="flex flex-wrap items-end gap-4">
        <div className="space-y-2">
          <Label htmlFor="type-filter">{t("filterType")}</Label>
          <Select
            value={typeFilter}
            onValueChange={(v) => applyFilter(() => setTypeFilter(v))}
          >
            <SelectTrigger id="type-filter" className="w-52">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("allTypes")}</SelectItem>
              {NOTE_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {t(type === "direct_customer" ? "directCustomer" : type)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="date-from">{t("dateFrom")}</Label>
          <Input
            id="date-from"
            type="date"
            className="w-44"
            value={dateFrom}
            onChange={(e) => applyFilter(() => setDateFrom(e.target.value))}
          />
        </div>

        <div className="space-y-2">
          <Label htmlFor="date-to">{t("dateTo")}</Label>
          <Input
            id="date-to"
            type="date"
            className="w-44"
            value={dateTo}
            onChange={(e) => applyFilter(() => setDateTo(e.target.value))}
          />
        </div>

        {hasFilters && (
          <Button variant="outline" onClick={clearFilters}>
            {t("clearFilters")}
          </Button>
        )}
      </div>

      {isLoading && (
        <div className="space-y-2" data-testid="delivery-notes-loading">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <Alert variant="destructive">
          <AlertDescription>{tc("error")}</AlertDescription>
        </Alert>
      )}

      {!isLoading && !isError && data && (
        <>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/40">
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("documentNumber")}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("type")}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("partner")}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("documentDate")}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("source")}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("provenance")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.results.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-4 py-10 text-center text-muted-foreground"
                    >
                      <div className="flex flex-col items-center gap-2">
                        <FileText className="h-8 w-8 opacity-30" />
                        <span>{t("noNotes")}</span>
                      </div>
                    </td>
                  </tr>
                ) : (
                  data.results.map((note) => (
                    <tr
                      key={note.id}
                      className="border-b border-border last:border-0 hover:bg-muted/20"
                    >
                      <td className="px-4 py-3 font-medium text-foreground">
                        {note.document_number}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={TYPE_VARIANTS[note.type] ?? "outline"}>
                          {t(
                            note.type === "direct_customer"
                              ? "directCustomer"
                              : note.type
                          )}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {note.partner_name ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {note.document_date}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {note.source ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={note.uploaded ? "secondary" : "outline"}>
                          {note.uploaded ? t("uploaded") : t("systemGenerated")}
                        </Badge>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                {page} / {totalPages} — {data.total}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  {tc("previous")}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  {tc("next")}
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
