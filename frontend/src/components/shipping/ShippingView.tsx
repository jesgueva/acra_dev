"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { apiClient } from "@/src/lib/api-client";
import { useAuth } from "@/src/contexts/AuthContext";
import { PRIVILEGES } from "@/src/lib/privileges";
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
import { Plus, Trash2, PackageCheck } from "lucide-react";
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
  product_name: string | null;
  lot_number: string | null;
}

interface Shipment {
  id: number;
  delivery_note_id: number | null;
  contact_id: number | null;
  contact_name: string | null;
  carrier_id: number | null;
  carrier_name: string | null;
  bol_number: string;
  shipment_date: string;
  notes: string | null;
  type: string;
  /** §4.3 — originating stock location, direct-customer shipments only. */
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

interface LineItem {
  lot_id: string;
  quantity: string;
}

const EMPTY_LINE: LineItem = { lot_id: "", quantity: "" };

// §4.3 — the two outbound delivery-note flavours. These are `delivery_notes.type` values.
const DIRECT_CUSTOMER = "direct_customer";
const TRANSFER = "transfer";

const TYPE_VARIANTS: Record<string, "default" | "secondary" | "outline"> = {
  [DIRECT_CUSTOMER]: "default",
  [TRANSFER]: "secondary",
};

// ── Component ────────────────────────────────────────────────────────────────

export function ShippingView() {
  const t = useTranslations("shipping");
  const tc = useTranslations("common");
  const queryClient = useQueryClient();
  const { hasPrivilege } = useAuth();

  // `shipping.view` and `shipping.create` are granted separately (ACR-35) — the supervisor reads
  // the log but cannot book a shipment, so don't offer them a button that would 403 on submit.
  const canCreate = hasPrivilege(PRIVILEGES.SHIPPING_CREATE);

  const [page, setPage] = useState(1);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [detailShipment, setDetailShipment] = useState<Shipment | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [form, setForm] = useState({
    contact_id: "",
    carrier_id: "",
    bol_number: "",
    shipment_date: "",
    type: DIRECT_CUSTOMER,
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

  // ── Mutations ──────────────────────────────────────────────────────────────

  const createMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiClient.post("/shipments", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["shipments"] });
      setDialogOpen(false);
      resetForm();
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setFormError(detail ?? tc("error"));
    },
  });

  // ── Helpers ────────────────────────────────────────────────────────────────

  function typeLabel(type: string) {
    return type === TRANSFER ? t("transfer") : t("directCustomer");
  }

  function resetForm() {
    setForm({
      contact_id: "",
      carrier_id: "",
      bol_number: "",
      shipment_date: "",
      type: DIRECT_CUSTOMER,
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
      }));

    if (items.length === 0) {
      setFormError("At least one valid lot line is required.");
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
    // §4.3 — only a direct-customer note carries a source.
    if (form.type === DIRECT_CUSTOMER && form.source.trim()) {
      body.source = form.source.trim();
    }

    createMutation.mutate(body);
  }

  const totalPages = data ? Math.ceil(data.total / data.page_size) : 1;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 p-6">
      <PageHeader title={t("title")} description={t("subtitle")}>
        {canCreate && (
          <Button onClick={openCreate}>
            <Plus className="mr-2 h-4 w-4" />
            {t("newShipment")}
          </Button>
        )}
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
          <div className="rounded-md border border-border">
            <table className="w-full text-sm">
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
                  <th className="px-4 py-3 text-right font-medium text-muted-foreground">
                    {t("items")}
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
                        <PackageCheck className="h-8 w-8 opacity-30" />
                        <span>{t("noShipments")}</span>
                      </div>
                    </td>
                  </tr>
                ) : (
                  data.results.map((s) => (
                    <tr
                      key={s.id}
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
                        <Badge
                          variant={TYPE_VARIANTS[s.type] ?? "outline"}
                          className="capitalize"
                        >
                          {typeLabel(s.type)}
                        </Badge>
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
                    // Clear a stale source when switching away from direct customer,
                    // which the API rejects (§4.3).
                    setForm({
                      ...form,
                      type: v,
                      source: v === DIRECT_CUSTOMER ? form.source : "",
                    })
                  }
                >
                  <SelectTrigger id="type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={DIRECT_CUSTOMER}>{t("directCustomer")}</SelectItem>
                    <SelectItem value={TRANSFER}>{t("transfer")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="source">{t("source")}</Label>
                <Input
                  id="source"
                  value={form.source}
                  onChange={(e) => setForm({ ...form, source: e.target.value })}
                  disabled={form.type !== DIRECT_CUSTOMER}
                  maxLength={50}
                  placeholder={t("sourcePlaceholder")}
                />
              </div>
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

              <div className="rounded-md border border-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/40">
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                        {t("lotId")}
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-muted-foreground">
                        {t("quantity")}
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
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? tc("loading") : t("submit")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* ── Shipment Detail Dialog ──────────────────────────────────────── */}
      <Dialog open={detailOpen} onOpenChange={setDetailOpen}>
        <DialogContent className="sm:max-w-lg">
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
                  <Badge
                    variant={TYPE_VARIANTS[detailShipment.type] ?? "outline"}
                    className="capitalize"
                  >
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
              <div className="rounded-md border border-border">
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
                      </tr>
                    ))}
                  </tbody>
                </table>
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
