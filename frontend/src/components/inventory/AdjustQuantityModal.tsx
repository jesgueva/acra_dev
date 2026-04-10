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

interface AdjustQuantityModalProps {
  item: InventoryLot | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function AdjustQuantityModal({
  item,
  onClose,
  onSuccess,
}: AdjustQuantityModalProps) {
  const t = useTranslations("inventory");
  const tc = useTranslations("common");
  const [delta, setDelta] = useState("");
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const open = item !== null;

  const handleClose = () => {
    setDelta("");
    setReason("");
    setConfirming(false);
    setError(null);
    onClose();
  };

  const handleSubmit = () => {
    setError(null);
    const d = Number(delta);
    if (isNaN(d) || d === 0) {
      setError(t("adjustNonZeroError"));
      return;
    }
    if (!reason.trim()) {
      setError(t("reasonRequired"));
      return;
    }
    setConfirming(true);
  };

  const handleConfirm = async () => {
    if (!item) return;
    setIsLoading(true);
    setError(null);
    try {
      await apiClient.patch(`/inventory/${item.id}`, {
        delta: toStore(Number(delta)),
        reason,
      });
      onSuccess();
      handleClose();
    } catch {
      setError(t("adjustFailed"));
      setConfirming(false);
    } finally {
      setIsLoading(false);
    }
  };

  const previewQty = item
    ? toDisplay(item.quantity_on_hand + toStore(Number(delta) || 0))
    : "—";

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) handleClose(); }}>
      <DialogContent data-testid="adjust-modal">
        <DialogHeader>
          <DialogTitle>
            {t("adjustQuantityHeading", {
              name:
                item?.product_name ??
                (item ? t("lotShort", { id: item.id }) : ""),
            })}
          </DialogTitle>
          <DialogDescription>
            {t("adjustDialogDescription", {
              qty: item ? toDisplay(item.quantity_on_hand) : "—",
            })}
          </DialogDescription>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertDescription data-testid="adjust-error">{error}</AlertDescription>
          </Alert>
        )}

        {!confirming ? (
          <div className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="delta">{t("adjustAmount")}</Label>
              <Input
                id="delta"
                type="number"
                step="0.01"
                value={delta}
                onChange={(e) => setDelta(e.target.value)}
                placeholder={t("adjustPlaceholder")}
                data-testid="quantity-input"
              />
              {delta && !isNaN(Number(delta)) && (
                <p className="text-xs text-muted-foreground">
                  {t("newQuantity", { qty: previewQty })}
                </p>
              )}
            </div>
            <div className="space-y-1">
              <Label htmlFor="reason">{t("reason")}</Label>
              <Input
                id="reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder={t("reasonPlaceholder")}
                data-testid="reason-input"
              />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={handleClose}>
                {tc("cancel")}
              </Button>
              <Button onClick={handleSubmit}>{t("review")}</Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm">
              {t("adjustConfirmQuestion", {
                name: item?.product_name ?? (item ? t("lotShort", { id: item.id }) : ""),
                delta: `${Number(delta) >= 0 ? "+" : ""}${delta}`,
                qty: previewQty,
              })}
            </p>
            {reason && (
              <p className="text-sm text-muted-foreground">
                {t("reasonLine", { reason })}
              </p>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={() => setConfirming(false)}>
                {t("back")}
              </Button>
              <Button onClick={handleConfirm} disabled={isLoading} data-testid="confirm-adjust">
                {isLoading ? tc("saving") : t("confirm")}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
