"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { Plus, Trash2, PackageCheck, FileText } from "lucide-react";
import { toDisplay, toStore } from "@/src/lib/qty";

// ── Types ────────────────────────────────────────────────────────────────────

interface Contact {
  id: number;
  name: string;
  type: string;
}

interface ContactListResponse {
  results: Contact[];
  total: number;
}

interface ShipmentItem {
  id: number;
  lot_id: number;
  quantity: number;
  unit_price: number | null;
  product_name: string | null;
  lot_number: string | null;
}

interface Shipment {
  id: number;
  contact_id: number | null;
  contact_name: string | null;
  carrier_id: number | null;
  carrier_name: string | null;
  bol_number: string;
  shipment_date: string;
  notes: string | null;
  type: string;
  source: string | null;
  created_by: number;
  created_at: string;
  items: ShipmentItem[];
}

interface ShipmentListResponse {
  total: number;
  page: number;
  page_size: number;
  results: Shipment[];
}

interface InvoiceLine {
  id: number;
  shipment_item_id: number;
  description: string;
  quantity: number;
  unit_price: number;
  line_total: number;
}

interface Invoice {
  id: number;
  shipment_id: number;
  invoice_number: string;
  invoice_date: string;
  currency: string;
  subtotal_amount: number;
  tax_amount: number;
  total_amount: number;
  status: string;
  lines: InvoiceLine[];
}

interface LineItem {
  lot_id: string;
  quantity: string;
  unit_price: string;
}

const EMPTY_LINE: LineItem = { lot_id: "", quantity: "", unit_price: "" };

// Domain model §4.3 — the two outbound delivery-note flavors.
const TYPE_TRANSFER = "transfer";
const TYPE_DIRECT_CUSTOMER = "direct_customer";

const TYPE_VARIANTS: Record<string, "default" | "secondary" | "outline"> = {
  [TYPE_DIRECT_CUSTOMER]: "default",
  [TYPE_TRANSFER]: "secondary",
};

// ── Component ────────────────────────────────────────────────────────────────

export function ShippingView() {
  const t = useTranslations("shipping");
  const tc = useTranslations("common");
  const queryClient = useQueryClient();

  const [page, setPage] = useState(1);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [detailShipment, setDetailShipment] = useState<Shipment | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [invoiceError, setInvoiceError] = useState<string | null>(null);

  const [form, setForm] = useState({
    contact_id: "",
    carrier_id: "",
    bol_number: "",
    shipment_date: "",
    type: TYPE_DIRECT_CUSTOMER,
    source: "",
    notes: "",
  });
  const [lines, setLines] = useState<LineItem[]>([{ ...EMPTY_LINE }]);

  // ── Data queries ───────────────────────────────────────────────────────────

  const { data, isLoading, isError } = useQuery<ShipmentListResponse>({
    queryKey: ["shipments", page],
    queryFn: () =>
      apiClient
        .get("/shipments", { params: { page, page_size: 20 } })
        .then((r) => r.data),
  });

  const { data: clientsData } = useQuery<ContactListResponse>({
    queryKey: ["contacts-clients"],
    queryFn: () =>
      apiClient
        .get("/contacts", { params: { type: "client", page_size: 200 } })
        .then((r) => r.data),
    enabled: dialogOpen,
  });

  const { data: carriersData } = useQuery<ContactListResponse>({
    queryKey: ["contacts-carriers"],
    queryFn: () =>
      apiClient
        .get("/contacts", { params: { type: "carrier", page_size: 200 } })
        .then((r) => r.data),
    enabled: dialogOpen,
  });

  // A shipment either has an invoice or it does not — a 404 is the answer, not a failure.
  const { data: invoice, isLoading: invoiceLoading } = useQuery<Invoice | null>({
    queryKey: ["invoice", detailShipment?.id],
    queryFn: () =>
      apiClient
        .get(`/shipments/${detailShipment!.id}/invoice`)
        .then((r) => r.data)
        .catch((err) => {
          if (err?.response?.status === 404) return null;
          throw err;
        }),
    enabled: detailOpen && detailShipment != null,
    retry: false,
  });

  // ── Mutations ──────────────────────────────────────────────────────────────

  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiClient.post("/shipments", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["shipments"] });
      setDialogOpen(false);
      resetForm();
    },
    onError: (err: unknown) => {
      setFormError(errorDetail(err) ?? tc("error"));
    },
  });

  const invoiceMutation = useMutation({
    mutationFn: (shipmentId: number) =>
      apiClient.post(`/shipments/${shipmentId}/invoice`).then((r) => r.data),
    onSuccess: (created: Invoice) => {
      queryClient.setQueryData(["invoice", created.shipment_id], created);
      setInvoiceError(null);
    },
    onError: (err: unknown) => {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setInvoiceError(
        status === 409 ? t("invoiceExists") : errorDetail(err) ?? tc("error")
      );
    },
  });

  // ── Helpers ────────────────────────────────────────────────────────────────

  function errorDetail(err: unknown): string | null {
    const detail = (
      err as { response?: { data?: { detail?: unknown } } }
    )?.response?.data?.detail;
    if (typeof detail === "string") return detail;
    // FastAPI returns validation errors as a list of {loc, msg, …}; Pydantic prefixes messages
    // raised by a custom validator with "Value error, ", which means nothing to an operator.
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string } | undefined;
      if (first?.msg) return first.msg.replace(/^Value error,\s*/, "");
    }
    return null;
  }

  function resetForm() {
    setForm({
      contact_id: "",
      carrier_id: "",
      bol_number: "",
      shipment_date: "",
      type: TYPE_DIRECT_CUSTOMER,
      source: "",
      notes: "",
    });
    setLines([{ ...EMPTY_LINE }]);
    setFormError(null);
  }

  function openCreate() {
    resetForm();
    setDialogOpen(true);
  }

  function openDetail(s: Shipment) {
    setDetailShipment(s);
    setInvoiceError(null);
    setDetailOpen(true);
  }

  function addLine() {
    setLines((prev) => [...prev, { ...EMPTY_LINE }]);
  }

  function removeLine(idx: number) {
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }

  function updateLine(idx: number, field: keyof LineItem, value: string) {
    setLines((prev) =>
      prev.map((l, i) => (i === idx ? { ...l, [field]: value } : l))
    );
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    const items = lines
      .filter((l) => l.lot_id && l.quantity)
      .map((l) => ({
        lot_id: parseInt(l.lot_id, 10),
        quantity: toStore(parseFloat(l.quantity)),
        ...(l.unit_price ? { unit_price: toStore(parseFloat(l.unit_price)) } : {}),
      }));

    if (items.length === 0) {
      setFormError(t("noValidLines"));
      return;
    }

    const body: Record<string, unknown> = {
      bol_number: form.bol_number,
      shipment_date: form.shipment_date,
      type: form.type,
      items,
    };
    if (form.contact_id) body.contact_id = parseInt(form.contact_id, 10);
    if (form.carrier_id) body.carrier_id = parseInt(form.carrier_id, 10);
    if (form.notes) body.notes = form.notes;
    if (form.type === TYPE_DIRECT_CUSTOMER && form.source.trim()) {
      body.source = form.source.trim();
    }

    createMutation.mutate(body);
  }

  function typeLabel(type: string) {
    return type === TYPE_TRANSFER ? t("transfer") : t("directCustomer");
  }

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 p-6">
      <PageHeader title={t("title")} description={t("subtitle")}>
        <Button onClick={openCreate} data-testid="new-shipment-button">
          <Plus className="mr-2 h-4 w-4" />
          {t("newShipment")}
        </Button>
      </PageHeader>

      {isLoading && (
        <div className="space-y-2">
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
            <table className="w-full text-sm" data-testid="shipment-table">
              <thead>
                <tr className="border-b border-border bg-muted/40">
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("bolNumber")}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("shipmentDate")}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("client")}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("carrier")}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("type")}
                  </th>
                  <th className="px-4 py-3 text-left font-medium text-muted-foreground">
                    {t("source")}
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">
                    {t("items")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.results.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="px-4 py-10 text-center text-muted-foreground"
                    >
                      <div className="flex flex-col items-center gap-2">
                        <PackageCheck className="h-8 w-8 opacity-30" />
                        <span>{t("noShipments")}</span>
                      </div>
                    </td>
                  </tr>
                ) : (
                  data.results.map((s) => (
                    <tr
                      key={s.id}
                      data-testid={`shipment-row-${s.id}`}
                      className="cursor-pointer border-b border-border last:border-0 hover:bg-muted/20"
                      onClick={() => openDetail(s)}
                    >
                      <td className="px-4 py-3 font-medium text-foreground">
                        {s.bol_number}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {s.shipment_date}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {s.contact_name ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {s.carrier_name ?? "—"}
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={TYPE_VARIANTS[s.type] ?? "outline"}>
                          {typeLabel(s.type)}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {s.source ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-right text-muted-foreground">
                        {s.items.length}
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
                Page {page} of {totalPages} — {data.total} total
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── Create Shipment Dialog ──────────────────────────────────────── */}
      <Dialog
        open={dialogOpen}
        onOpenChange={(open) => {
          setDialogOpen(open);
          if (!open) resetForm();
        }}
      >
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t("newShipment")}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="bol_number">{t("bolNumber")} *</Label>
                <Input
                  id="bol_number"
                  data-testid="bol-input"
                  value={form.bol_number}
                  onChange={(e) => setForm({ ...form, bol_number: e.target.value })}
                  required
                  maxLength={100}
                  placeholder="AV25-10228"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="shipment_date">{t("shipmentDate")} *</Label>
                <Input
                  id="shipment_date"
                  data-testid="date-input"
                  type="date"
                  value={form.shipment_date}
                  onChange={(e) => setForm({ ...form, shipment_date: e.target.value })}
                  required
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="contact_id">{t("client")}</Label>
                <Select
                  value={form.contact_id}
                  onValueChange={(v) => setForm({ ...form, contact_id: v })}
                >
                  <SelectTrigger id="contact_id">
                    <SelectValue placeholder={t("selectClient")} />
                  </SelectTrigger>
                  <SelectContent>
                    {clientsData?.results.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="carrier_id">{t("carrier")}</Label>
                <Select
                  value={form.carrier_id}
                  onValueChange={(v) => setForm({ ...form, carrier_id: v })}
                >
                  <SelectTrigger id="carrier_id">
                    <SelectValue placeholder={t("selectCarrier")} />
                  </SelectTrigger>
                  <SelectContent>
                    {carriersData?.results.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="type">{t("type")}</Label>
                <Select
                  value={form.type}
                  onValueChange={(v) =>
                    setForm({
                      // `source` is meaningless on a Transfer note and the API rejects it, so
                      // drop it as the type changes rather than failing the submit later.
                      ...form,
                      type: v,
                      source: v === TYPE_DIRECT_CUSTOMER ? form.source : "",
                    })
                  }
                >
                  <SelectTrigger id="type" data-testid="type-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={TYPE_DIRECT_CUSTOMER}>
                      {t("directCustomer")}
                    </SelectItem>
                    <SelectItem value={TYPE_TRANSFER}>{t("transfer")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {form.type === TYPE_DIRECT_CUSTOMER && (
                <div className="space-y-2">
                  <Label htmlFor="source">{t("source")}</Label>
                  <Input
                    id="source"
                    data-testid="source-input"
                    value={form.source}
                    onChange={(e) => setForm({ ...form, source: e.target.value })}
                    maxLength={50}
                    placeholder={t("sourcePlaceholder")}
                  />
                  <p className="text-xs text-muted-foreground">{t("sourceHint")}</p>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="notes">{t("notes")}</Label>
              <Input
                id="notes"
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder={t("notesPlaceholder")}
              />
            </div>

            <Separator />

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label>{t("items")}</Label>
                <Button type="button" variant="outline" size="sm" onClick={addLine}>
                  <Plus className="mr-1 h-3 w-3" />
                  {t("addItem")}
                </Button>
              </div>

              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/40">
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                        {t("lotId")}
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                        {t("quantity")}
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                        {t("unitPrice")}
                      </th>
                      <th className="w-10" />
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((line, idx) => (
                      <tr key={idx} className="border-b border-border last:border-0">
                        <td className="px-3 py-2">
                          <Input
                            type="number"
                            min="1"
                            value={line.lot_id}
                            onChange={(e) => updateLine(idx, "lot_id", e.target.value)}
                            placeholder="Lot ID"
                            className="h-8"
                            data-testid={`lot-input-${idx}`}
                            aria-label={`${t("lotId")} ${idx + 1}`}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <Input
                            type="number"
                            min="0.01"
                            step="0.01"
                            value={line.quantity}
                            onChange={(e) => updateLine(idx, "quantity", e.target.value)}
                            placeholder="0.00"
                            className="h-8"
                            data-testid={`qty-input-${idx}`}
                            aria-label={`${t("quantity")} ${idx + 1}`}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <Input
                            type="number"
                            min="0"
                            step="0.01"
                            value={line.unit_price}
                            onChange={(e) =>
                              updateLine(idx, "unit_price", e.target.value)
                            }
                            placeholder="0.00"
                            className="h-8"
                            data-testid={`price-input-${idx}`}
                            aria-label={`${t("unitPrice")} ${idx + 1}`}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-8 w-8 p-0 text-destructive hover:text-destructive"
                            onClick={() => removeLine(idx)}
                            disabled={lines.length <= 1}
                            aria-label={t("removeItem")}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {formError && (
              <Alert variant="destructive">
                <AlertDescription>{formError}</AlertDescription>
              </Alert>
            )}

            <Separator />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setDialogOpen(false)}
              >
                {tc("cancel")}
              </Button>
              <Button type="submit" data-testid="submit-shipment" disabled={createMutation.isPending}>
                {createMutation.isPending ? tc("loading") : t("submit")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Shipment Detail Dialog ──────────────────────────────────────── */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{detailShipment?.bol_number}</DialogTitle>
          </DialogHeader>
          {detailShipment && (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-muted-foreground">{t("client")}</p>
                  <p className="font-medium">{detailShipment.contact_name ?? "—"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("carrier")}</p>
                  <p className="font-medium">{detailShipment.carrier_name ?? "—"}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("shipmentDate")}</p>
                  <p className="font-medium">{detailShipment.shipment_date}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">{t("type")}</p>
                  <Badge variant={TYPE_VARIANTS[detailShipment.type] ?? "outline"}>
                    {typeLabel(detailShipment.type)}
                  </Badge>
                </div>
                {detailShipment.source && (
                  <div>
                    <p className="text-muted-foreground">{t("source")}</p>
                    <p className="font-medium">{detailShipment.source}</p>
                  </div>
                )}
              </div>
              {detailShipment.notes && (
                <p className="text-muted-foreground">{detailShipment.notes}</p>
              )}
              <Separator />
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/40">
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                        {t("lotNumber")}
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                        {t("productName")}
                      </th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                        {t("quantity")}
                      </th>
                      <th className="px-3 py-2 text-right font-medium text-muted-foreground">
                        {t("unitPrice")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailShipment.items.map((item) => (
                      <tr
                        key={item.id}
                        className="border-b border-border last:border-0"
                      >
                        <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                          {item.lot_number ?? `#${item.lot_id}`}
                        </td>
                        <td className="px-3 py-2">{item.product_name ?? "—"}</td>
                        <td className="px-3 py-2 text-right font-medium">
                          {toDisplay(item.quantity)}
                        </td>
                        <td className="px-3 py-2 text-right text-muted-foreground">
                          {item.unit_price == null ? "—" : toDisplay(item.unit_price)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <Separator />

              {/* ── Invoice ──────────────────────────────────────────── */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label>{t("invoice")}</Label>
                  {!invoice && !invoiceLoading && (
                    <Button
                      type="button"
                      size="sm"
                      data-testid="generate-invoice"
                      onClick={() => invoiceMutation.mutate(detailShipment.id)}
                      disabled={invoiceMutation.isPending}
                    >
                      <FileText className="mr-1 h-3.5 w-3.5" />
                      {invoiceMutation.isPending
                        ? tc("loading")
                        : t("generateInvoice")}
                    </Button>
                  )}
                </div>

                {invoiceLoading && <Skeleton className="h-16 w-full" />}

                {!invoiceLoading && !invoice && !invoiceError && (
                  <p className="text-muted-foreground">{t("noInvoice")}</p>
                )}

                {invoiceError && (
                  <Alert variant="destructive">
                    <AlertDescription>{invoiceError}</AlertDescription>
                  </Alert>
                )}

                {invoice && (
                  <div
                    className="space-y-2 rounded-md border border-border p-3"
                    data-testid="invoice-panel"
                  >
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-muted-foreground">{t("invoiceNumber")}</p>
                        <p className="font-mono font-medium" data-testid="invoice-number">
                          {invoice.invoice_number}
                        </p>
                      </div>
                      <div>
                        <p className="text-muted-foreground">{t("invoiceDate")}</p>
                        <p className="font-medium">{invoice.invoice_date}</p>
                      </div>
                    </div>
                    <Separator />
                    <div className="space-y-1">
                      {invoice.lines.map((line) => (
                        <div
                          key={line.id}
                          className="flex justify-between gap-3 text-xs"
                        >
                          <span className="text-muted-foreground">
                            {line.description}
                          </span>
                          <span className="font-medium">
                            {toDisplay(line.line_total)}
                          </span>
                        </div>
                      ))}
                    </div>
                    <Separator />
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground">
                        {t("invoiceSubtotal")}
                      </span>
                      <span>{toDisplay(invoice.subtotal_amount)}</span>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground">{t("invoiceTax")}</span>
                      <span>{toDisplay(invoice.tax_amount)}</span>
                    </div>
                    <div className="flex justify-between font-medium">
                      <span>{t("invoiceTotal")}</span>
                      <span data-testid="invoice-total">
                        {toDisplay(invoice.total_amount)} {invoice.currency}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setDetailOpen(false)}>
              {tc("cancel")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
