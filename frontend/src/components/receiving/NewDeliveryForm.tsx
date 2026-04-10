"use client";

import React, { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiClient, getResponseStatus } from "@/src/lib/api-client";
import type { OCRResult } from "./OCRUploader";

interface ItemRow {
  item_name: string;
  description: string;
  quantity: string;
  pallets: string;
  units_per_pallet: string;
}

const emptyRow = (): ItemRow => ({
  item_name: "",
  description: "",
  quantity: "",
  pallets: "",
  units_per_pallet: "",
});

function ocrItemsToRows(items: NonNullable<OCRResult["items"]>): ItemRow[] {
  return items.map((it) => ({
    item_name: it.item_name,
    description: it.description ?? "",
    quantity: String(it.quantity),
    pallets: it.pallets != null ? String(it.pallets) : "",
    units_per_pallet: it.units_per_pallet != null ? String(it.units_per_pallet) : "",
  }));
}

function computeLeftover(row: ItemRow): number | null {
  const qty = parseFloat(row.quantity);
  const pallets = parseInt(row.pallets, 10);
  const upm = parseInt(row.units_per_pallet, 10);
  if (isNaN(qty) || isNaN(pallets) || isNaN(upm)) return null;
  const diff = pallets * upm - qty;
  return diff !== 0 ? diff : null;
}

const TRANSFER_RE = /transfer/i;

interface NewDeliveryFormProps {
  onSuccess: () => void;
  initialValues?: Partial<OCRResult>;
  ocrHighlightedFields?: string[];
}

export default function NewDeliveryForm({
  onSuccess,
  initialValues,
  ocrHighlightedFields = [],
}: NewDeliveryFormProps) {
  const t = useTranslations("receiving");

  const [supplier, setSupplier] = useState(initialValues?.supplier ?? "");
  const [carrier, setCarrier] = useState(initialValues?.carrier ?? "");
  const [bolReference, setBolReference] = useState(initialValues?.bol_reference ?? "");
  const [deliveryDate, setDeliveryDate] = useState(initialValues?.delivery_date ?? "");
  const [items, setItems] = useState<ItemRow[]>(
    initialValues?.items?.length ? ocrItemsToRows(initialValues.items) : [emptyRow()]
  );
  const [notes, setNotes] = useState("");
  const [supplierLocked, setSupplierLocked] = useState(false);
  const [showProceedAnyway, setShowProceedAnyway] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!initialValues) return;
    if (initialValues.supplier) setSupplier(initialValues.supplier);
    if (initialValues.carrier) setCarrier(initialValues.carrier);
    if (initialValues.bol_reference) setBolReference(initialValues.bol_reference);
    if (initialValues.delivery_date) setDeliveryDate(initialValues.delivery_date);
    if (initialValues.items?.length) setItems(ocrItemsToRows(initialValues.items));
  }, [initialValues]);

  // Auto-detect transfer carrier
  useEffect(() => {
    if (TRANSFER_RE.test(carrier)) {
      setSupplier("Internal");
      setSupplierLocked(true);
    } else {
      setSupplierLocked(false);
    }
  }, [carrier]);

  function isHighlighted(field: string) {
    return ocrHighlightedFields.includes(field);
  }

  function updateItem(index: number, field: keyof ItemRow, value: string) {
    setItems((prev) =>
      prev.map((row, i) => (i === index ? { ...row, [field]: value } : row))
    );
  }

  function addItem() {
    setItems((prev) => [...prev, emptyRow()]);
  }

  function removeItem(index: number) {
    setItems((prev) => prev.filter((_, i) => i !== index));
  }

  async function submitDelivery(force = false) {
    setLoading(true);
    setShowProceedAnyway(false);
    try {
      await apiClient.post("/deliveries", {
        supplier,
        carrier,
        bol_reference: bolReference,
        delivery_date: deliveryDate,
        notes: notes || undefined,
        force,
        items: items.map((row) => ({
          item_name: row.item_name,
          description: row.description || undefined,
          quantity: Number(row.quantity),
          pallets: row.pallets ? Number(row.pallets) : undefined,
          units_per_pallet: row.units_per_pallet ? Number(row.units_per_pallet) : undefined,
        })),
      });
      onSuccess();
      setNotes("");
      setItems([emptyRow()]);
      setCarrier("");
      setSupplier("");
      setBolReference("");
      setDeliveryDate("");
    } catch (err: unknown) {
      if (getResponseStatus(err) === 409) {
        setShowProceedAnyway(true);
      }
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submitDelivery(false);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Header fields */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="carrier">{t("carrier")}</Label>
          <Input
            id="carrier"
            value={carrier}
            onChange={(e) => setCarrier(e.target.value)}
            className={isHighlighted("carrier") ? "border-yellow-400 bg-yellow-50/10" : ""}
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="supplier">
            {t("supplier")}
            {supplierLocked && (
              <span className="ml-2 text-xs text-muted-foreground">({t("internalSupplier")})</span>
            )}
          </Label>
          <Input
            id="supplier"
            value={supplier}
            onChange={(e) => !supplierLocked && setSupplier(e.target.value)}
            readOnly={supplierLocked}
            className={[
              isHighlighted("supplier") ? "border-yellow-400 bg-yellow-50/10" : "",
              supplierLocked ? "opacity-60 cursor-not-allowed" : "",
            ].join(" ")}
            required
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="bol_reference">{t("bolNumber")}</Label>
          <Input
            id="bol_reference"
            value={bolReference}
            onChange={(e) => {
              setBolReference(e.target.value);
              setShowProceedAnyway(false);
            }}
            className={isHighlighted("bol_reference") ? "border-yellow-400 bg-yellow-50/10" : ""}
            required
          />
          {showProceedAnyway && (
            <p className="text-sm text-destructive" role="alert">
              {t("bolDuplicate")}
            </p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="delivery_date">{t("deliveryDate")}</Label>
          <Input
            id="delivery_date"
            value={deliveryDate}
            onChange={(e) => setDeliveryDate(e.target.value)}
            className={isHighlighted("delivery_date") ? "border-yellow-400 bg-yellow-50/10" : ""}
            placeholder="DD/MM/YY"
            required
          />
        </div>
      </div>

      {showProceedAnyway && (
        <div className="rounded-md bg-yellow-50/10 border border-yellow-400/50 px-4 py-3 flex items-center justify-between gap-4">
          <p className="text-sm text-yellow-600 dark:text-yellow-400">{t("bolDuplicate")}</p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => submitDelivery(true)}
            disabled={loading}
          >
            {t("proceedAnyway")}
          </Button>
        </div>
      )}

      {/* Item rows */}
      <div className="space-y-3">
        {items.map((row, index) => {
          const leftover = computeLeftover(row);
          return (
            <div key={index} className="rounded-md border p-3 space-y-2">
              <div className="grid grid-cols-[1fr_1fr] gap-2">
                <div className="space-y-1">
                  <Label htmlFor={`item_name_${index}`}>{t("itemName")}</Label>
                  <Input
                    id={`item_name_${index}`}
                    value={row.item_name}
                    onChange={(e) => updateItem(index, "item_name", e.target.value)}
                    className={
                      isHighlighted(`items.${index}.item_name`) ? "border-yellow-400 bg-yellow-50/10" : ""
                    }
                    required
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`description_${index}`}>{t("description")}</Label>
                  <Input
                    id={`description_${index}`}
                    value={row.description}
                    onChange={(e) => updateItem(index, "description", e.target.value)}
                    className={
                      isHighlighted(`items.${index}.description`) ? "border-yellow-400 bg-yellow-50/10" : ""
                    }
                  />
                </div>
              </div>
              <div className="grid grid-cols-[100px_80px_80px_1fr_auto] gap-2 items-end">
                <div className="space-y-1">
                  <Label htmlFor={`quantity_${index}`}>{t("quantity")}</Label>
                  <Input
                    id={`quantity_${index}`}
                    type="number"
                    min="0"
                    step="any"
                    value={row.quantity}
                    onChange={(e) => updateItem(index, "quantity", e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`pallets_${index}`}>{t("pallets")}</Label>
                  <Input
                    id={`pallets_${index}`}
                    type="number"
                    min="0"
                    value={row.pallets}
                    onChange={(e) => updateItem(index, "pallets", e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`upm_${index}`}>{t("unitsPerPallet")}</Label>
                  <Input
                    id={`upm_${index}`}
                    type="number"
                    min="0"
                    value={row.units_per_pallet}
                    onChange={(e) => updateItem(index, "units_per_pallet", e.target.value)}
                  />
                </div>
                <div className="space-y-1">
                  <Label>{t("leftover")}</Label>
                  <div
                    className={`h-9 flex items-center px-3 rounded-md border text-sm font-mono ${
                      leftover != null
                        ? "border-amber-400 bg-amber-50/10 text-amber-600 dark:text-amber-400"
                        : "border-border text-muted-foreground"
                    }`}
                  >
                    {leftover != null ? `${leftover > 0 ? "+" : ""}${leftover.toFixed(3)}` : "—"}
                  </div>
                </div>
                {items.length > 1 && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={t("removeItem")}
                    onClick={() => removeItem(index)}
                    className="mb-0.5"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Notes */}
      <div className="space-y-1.5">
        <Label htmlFor="notes">{t("notes")}</Label>
        <textarea
          id="notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-none"
          placeholder={t("notesPlaceholder")}
        />
      </div>

      <div className="flex items-center gap-3">
        <Button type="button" variant="outline" onClick={addItem}>
          <Plus className="h-4 w-4 mr-1" />
          {t("addItem")}
        </Button>

        <Button type="submit" disabled={loading}>
          {loading ? (
            <Loader2 className="animate-spin" aria-label="loading" />
          ) : (
            t("submit")
          )}
        </Button>
      </div>
    </form>
  );
}
