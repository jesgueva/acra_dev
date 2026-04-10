"use client";

import React, { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { apiClient, getResponseStatus } from "@/src/lib/api-client";
import { toStore } from "@/src/lib/qty";
import type { OCRResult } from "./OCRUploader";

interface ContactOption {
  id: number;
  name: string;
  type: string;
}

interface ProductOption {
  id: number;
  name: string;
  category: string;
}

interface ItemRow {
  product_id: number | null;
  description: string;
  quantity: string;        // display units, e.g. "50.25"
  pallets: string;
  units_per_pallet: string;
}

const emptyRow = (): ItemRow => ({
  product_id: null,
  description: "",
  quantity: "",
  pallets: "",
  units_per_pallet: "",
});

function computeLeftover(row: ItemRow): number | null {
  const qty = parseFloat(row.quantity);
  const pallets = parseInt(row.pallets, 10);
  const upm = parseInt(row.units_per_pallet, 10);
  if (isNaN(qty) || isNaN(pallets) || isNaN(upm)) return null;
  const diff = pallets * upm - qty;  // display units
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

  const [contactId, setContactId] = useState<number | null>(null);
  const [carrierId, setCarrierId] = useState<number | null>(null);
  const [supplierLocked, setSupplierLocked] = useState(false);
  const [bolReference, setBolReference] = useState(initialValues?.bol_reference ?? "");
  const [deliveryDate, setDeliveryDate] = useState(initialValues?.delivery_date ?? "");
  const [notes, setNotes] = useState("");
  const [items, setItems] = useState<ItemRow[]>([emptyRow()]);
  const [showProceedAnyway, setShowProceedAnyway] = useState(false);
  const [loading, setLoading] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  const { data: contactsData } = useQuery({
    queryKey: ["contacts-for-delivery"],
    queryFn: () =>
      apiClient
        .get<{ results: ContactOption[] }>("/contacts?page_size=200")
        .then((r) => r.data.results),
  });

  const { data: productsData } = useQuery({
    queryKey: ["products-for-delivery"],
    queryFn: () =>
      apiClient
        .get<{ results: ProductOption[] }>("/products?page_size=200")
        .then((r) => r.data.results),
  });

  const contacts = contactsData ?? [];
  const products = productsData ?? [];
  const providers = contacts.filter((c) => c.type === "provider");
  const carriers = contacts.filter((c) => c.type === "carrier");

  // OCR pre-fill by name matching
  useEffect(() => {
    if (!initialValues) return;
    if (initialValues.bol_reference) setBolReference(initialValues.bol_reference);
    if (initialValues.delivery_date) setDeliveryDate(initialValues.delivery_date);

    if (contacts.length > 0) {
      if (initialValues.supplier) {
        const match = contacts.find(
          (c) => c.name.toLowerCase() === initialValues.supplier?.toLowerCase()
        );
        if (match) setContactId(match.id);
      }
      if (initialValues.carrier) {
        const match = contacts.find(
          (c) => c.name.toLowerCase() === initialValues.carrier?.toLowerCase()
        );
        if (match) setCarrierId(match.id);
      }
    }

    if (initialValues.items?.length && products.length > 0) {
      setItems(
        initialValues.items.map((it) => {
          const match = products.find(
            (p) => p.name.toLowerCase() === it.item_name?.toLowerCase()
          );
          return {
            product_id: match?.id ?? null,
            description: it.description ?? "",
            quantity: it.quantity != null ? String(it.quantity) : "",
            pallets: it.pallets != null ? String(it.pallets) : "",
            units_per_pallet: it.units_per_pallet != null ? String(it.units_per_pallet) : "",
          };
        })
      );
    }
  }, [initialValues, contacts, products]);

  // Transfer detection: carrier name matches /transfer/i → lock to "Internal" provider
  useEffect(() => {
    if (carrierId == null) {
      setSupplierLocked(false);
      return;
    }
    const carrierContact = contacts.find((c) => c.id === carrierId);
    if (carrierContact && TRANSFER_RE.test(carrierContact.name)) {
      const internal = contacts.find(
        (c) => c.name.toLowerCase() === "internal" && c.type === "provider"
      );
      if (internal) setContactId(internal.id);
      setSupplierLocked(true);
    } else {
      setSupplierLocked(false);
    }
  }, [carrierId, contacts]);

  function isHighlighted(field: string) {
    return ocrHighlightedFields.includes(field);
  }

  function updateItem(index: number, field: keyof ItemRow, value: string | number | null) {
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
    const missingProduct = items.some((row) => row.product_id == null);
    if (missingProduct) {
      setValidationError(t("productRequired"));
      return;
    }
    setValidationError(null);
    setLoading(true);
    setShowProceedAnyway(false);
    try {
      await apiClient.post("/deliveries", {
        contact_id: contactId,
        carrier_id: carrierId,
        bol_reference: bolReference,
        delivery_date: deliveryDate,
        notes: notes || undefined,
        force,
        items: items.map((row) => ({
          product_id: row.product_id,
          description: row.description || undefined,
          quantity: toStore(parseFloat(row.quantity)),
          pallets: row.pallets ? Number(row.pallets) : undefined,
          units_per_pallet: row.units_per_pallet ? Number(row.units_per_pallet) : undefined,
        })),
      });
      onSuccess();
      setNotes("");
      setItems([emptyRow()]);
      setCarrierId(null);
      setContactId(null);
      setBolReference("");
      setDeliveryDate("");
      setSupplierLocked(false);
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
        {/* Carrier select */}
        <div className="space-y-1.5">
          <Label>{t("carrier")}</Label>
          <Select
            value={carrierId?.toString() ?? ""}
            onValueChange={(v) => setCarrierId(v ? Number(v) : null)}
          >
            <SelectTrigger
              className={isHighlighted("carrier") ? "border-yellow-400 bg-yellow-50/10" : ""}
            >
              <SelectValue placeholder={t("selectCarrier")} />
            </SelectTrigger>
            <SelectContent>
              {carriers.map((c) => (
                <SelectItem key={c.id} value={c.id.toString()}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Supplier / provider select */}
        <div className="space-y-1.5">
          <Label>
            {t("supplier")}
            {supplierLocked && (
              <span className="ml-2 text-xs text-muted-foreground">
                ({t("internalSupplier")})
              </span>
            )}
          </Label>
          <Select
            value={contactId?.toString() ?? ""}
            onValueChange={(v) => !supplierLocked && setContactId(v ? Number(v) : null)}
            disabled={supplierLocked}
          >
            <SelectTrigger
              className={[
                isHighlighted("supplier") ? "border-yellow-400 bg-yellow-50/10" : "",
                supplierLocked ? "opacity-60" : "",
              ].join(" ")}
            >
              <SelectValue placeholder={t("selectProvider")} />
            </SelectTrigger>
            <SelectContent>
              {providers.map((c) => (
                <SelectItem key={c.id} value={c.id.toString()}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* BOL reference */}
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
        </div>

        {/* Delivery date */}
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
              {/* Product select + description */}
              <div className="grid grid-cols-[1fr_1fr] gap-2">
                <div className="space-y-1">
                  <Label>{t("product")}</Label>
                  <Select
                    value={row.product_id?.toString() ?? ""}
                    onValueChange={(v) =>
                      updateItem(index, "product_id", v ? Number(v) : null)
                    }
                  >
                    <SelectTrigger
                      className={
                        isHighlighted(`items.${index}.product_id`)
                          ? "border-yellow-400 bg-yellow-50/10"
                          : ""
                      }
                    >
                      <SelectValue placeholder={t("selectProduct")} />
                    </SelectTrigger>
                    <SelectContent>
                      {products.map((p) => (
                        <SelectItem key={p.id} value={p.id.toString()}>
                          {p.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor={`description_${index}`}>{t("description")}</Label>
                  <Input
                    id={`description_${index}`}
                    value={row.description}
                    onChange={(e) => updateItem(index, "description", e.target.value)}
                    className={
                      isHighlighted(`items.${index}.description`)
                        ? "border-yellow-400 bg-yellow-50/10"
                        : ""
                    }
                  />
                </div>
              </div>

              {/* Quantity, pallets, u/pallet, leftover, remove */}
              <div className="grid grid-cols-[100px_80px_80px_1fr_auto] gap-2 items-end">
                <div className="space-y-1">
                  <Label htmlFor={`quantity_${index}`}>{t("quantity")}</Label>
                  <Input
                    id={`quantity_${index}`}
                    type="number"
                    min="0"
                    step="0.01"
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
                    {leftover != null
                      ? `${leftover > 0 ? "+" : ""}${leftover.toFixed(2)}`
                      : "—"}
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
        <Textarea
          id="notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          placeholder={t("notesPlaceholder")}
        />
      </div>

      {validationError && (
        <Alert variant="destructive">
          <AlertDescription>{validationError}</AlertDescription>
        </Alert>
      )}

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
