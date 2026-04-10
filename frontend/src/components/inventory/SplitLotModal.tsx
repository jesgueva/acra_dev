"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { apiClient } from "@/src/lib/api-client";
import { toDisplay, toStore } from "@/src/lib/qty";
import { InventoryLot } from "./types";

interface SplitLotModalProps {
  lot: InventoryLot | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function SplitLotModal({ lot, onClose, onSuccess }: SplitLotModalProps) {
  const t = useTranslations("inventory");
  const tc = useTranslations("common");
  const [splitQty, setSplitQty] = useState("");
  const [newLocation, setNewLocation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const open = lot !== null;

  const handleClose = () => {
    setSplitQty("");
    setNewLocation("");
    setError(null);
    onClose();
  };

  const handleSubmit = async () => {
    if (!lot) return;
    const qty = toStore(Number(splitQty));
    if (isNaN(qty) || qty <= 0) {
      setError(t("splitQtyInvalid"));
      return;
    }
    if (qty > lot.quantity_on_hand) {
      setError(
        t("splitQtyExceeds", {
          split: toDisplay(qty),
          total: toDisplay(lot.quantity_on_hand),
        })
      );
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      await apiClient.post(`/inventory/lots/${lot.id}/split`, {
        split_quantity: qty,
        storage_location: newLocation || undefined,
      });
      onSuccess();
      handleClose();
    } catch {
      setError(t("splitFailed"));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) handleClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {lot ? `${t("splitLotTitle")} — #${lot.id}` : t("splitLotTitle")}
          </DialogTitle>
          <DialogDescription>
            {t("splitDescription", {
              qty: lot ? toDisplay(lot.quantity_on_hand) : "—",
            })}
          </DialogDescription>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="split-qty">{t("quantityToSplit")}</Label>
            <Input
              id="split-qty"
              type="number"
              min="0.01"
              step="0.01"
              value={splitQty}
              onChange={(e) => setSplitQty(e.target.value)}
              placeholder={t("splitQtyPlaceholder")}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-location">{t("newLocationOptional")}</Label>
            <Input
              id="new-location"
              value={newLocation}
              onChange={(e) => setNewLocation(e.target.value)}
              placeholder={t("splitLocationPlaceholder")}
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            {tc("cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={isLoading || !splitQty}>
            {isLoading ? t("splitting") : t("split")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
