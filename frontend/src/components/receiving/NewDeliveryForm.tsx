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
  lot_batch_number: string;
  quantity: string;
  unit: string;
}

const emptyRow = (): ItemRow => ({
  item_name: "",
  lot_batch_number: "",
  quantity: "",
  unit: "",
});

function ocrItemsToRows(items: NonNullable<OCRResult["items"]>): ItemRow[] {
  return items.map((it) => ({
    item_name: it.item_name,
    lot_batch_number: it.lot_batch_number,
    quantity: String(it.quantity),
    unit: it.unit,
  }));
}

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
  const [bolNumber, setBolNumber] = useState(initialValues?.bol_number ?? "");
  const [items, setItems] = useState<ItemRow[]>(
    initialValues?.items?.length ? ocrItemsToRows(initialValues.items) : [emptyRow()]
  );
  const [showProceedAnyway, setShowProceedAnyway] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!initialValues) return;
    if (initialValues.supplier) setSupplier(initialValues.supplier);
    if (initialValues.bol_number) setBolNumber(initialValues.bol_number);
    if (initialValues.items?.length) setItems(ocrItemsToRows(initialValues.items));
  }, [initialValues]);

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
        bol_number: bolNumber,
        force,
        items: items.map((row) => ({
          item_name: row.item_name,
          lot_batch_number: row.lot_batch_number,
          quantity: Number(row.quantity),
          unit: row.unit,
        })),
      });
      onSuccess();
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
    <form onSubmit={handleSubmit} className="space-y-6">
      <div className="space-y-1.5">
        <Label htmlFor="supplier">{t("supplier")}</Label>
        <Input
          id="supplier"
          value={supplier}
          onChange={(e) => setSupplier(e.target.value)}
          className={isHighlighted("supplier") ? "border-yellow-400 bg-yellow-50" : ""}
          required
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="bol_number">{t("bolNumber")}</Label>
        <Input
          id="bol_number"
          value={bolNumber}
          onChange={(e) => {
            setBolNumber(e.target.value);
            setShowProceedAnyway(false);
          }}
          className={isHighlighted("bol_number") ? "border-yellow-400 bg-yellow-50" : ""}
          required
        />
        {showProceedAnyway && (
          <p className="text-sm text-destructive" role="alert">
            {t("bolDuplicate")}
          </p>
        )}
      </div>

      {showProceedAnyway && (
        <div className="rounded-md bg-yellow-50 border border-yellow-300 px-4 py-3 flex items-center justify-between gap-4">
          <p className="text-sm text-yellow-800">{t("bolDuplicate")}</p>
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

      <div className="space-y-3">
        {items.map((row, index) => (
          <div key={index} className="grid grid-cols-[1fr_1fr_80px_80px_auto] gap-2 items-end">
            <div className="space-y-1">
              <Label htmlFor={`item_name_${index}`}>{t("itemName")}</Label>
              <Input
                id={`item_name_${index}`}
                value={row.item_name}
                onChange={(e) => updateItem(index, "item_name", e.target.value)}
                className={
                  isHighlighted(`items.${index}.item_name`) ? "border-yellow-400 bg-yellow-50" : ""
                }
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`lot_batch_${index}`}>{t("lotBatch")}</Label>
              <Input
                id={`lot_batch_${index}`}
                value={row.lot_batch_number}
                onChange={(e) => updateItem(index, "lot_batch_number", e.target.value)}
                className={
                  isHighlighted(`items.${index}.lot_batch_number`)
                    ? "border-yellow-400 bg-yellow-50"
                    : ""
                }
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`quantity_${index}`}>{t("quantity")}</Label>
              <Input
                id={`quantity_${index}`}
                type="number"
                min="0"
                value={row.quantity}
                onChange={(e) => updateItem(index, "quantity", e.target.value)}
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor={`unit_${index}`}>{t("unit")}</Label>
              <Input
                id={`unit_${index}`}
                value={row.unit}
                onChange={(e) => updateItem(index, "unit", e.target.value)}
                required
              />
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
        ))}
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
