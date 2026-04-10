"use client";

import { useState } from "react";
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
      setError("Enter a non-zero adjustment amount.");
      return;
    }
    if (!reason.trim()) {
      setError("A reason is required.");
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
      setError("Failed to adjust quantity. Please try again.");
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
            Adjust Quantity — {item?.product_name ?? `Lot #${item?.id}`}
          </DialogTitle>
          <DialogDescription>
            Current quantity: <strong>{item ? toDisplay(item.quantity_on_hand) : "—"}</strong>.
            Enter a positive or negative adjustment.
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
              <Label htmlFor="delta">Adjustment Amount</Label>
              <Input
                id="delta"
                type="number"
                step="0.01"
                value={delta}
                onChange={(e) => setDelta(e.target.value)}
                placeholder="e.g. +10.00 or -5.00"
                data-testid="quantity-input"
              />
              {delta && !isNaN(Number(delta)) && (
                <p className="text-xs text-muted-foreground">
                  New quantity: {previewQty}
                </p>
              )}
            </div>
            <div className="space-y-1">
              <Label htmlFor="reason">Reason</Label>
              <Input
                id="reason"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Reason for adjustment"
                data-testid="reason-input"
              />
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button onClick={handleSubmit}>Review</Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm">
              Adjust <strong>{item?.product_name ?? `Lot #${item?.id}`}</strong> by{" "}
              <strong>{Number(delta) >= 0 ? "+" : ""}{delta}</strong>?
              New quantity: <strong>{previewQty}</strong>
            </p>
            {reason && <p className="text-sm text-muted-foreground">Reason: {reason}</p>}
            <DialogFooter>
              <Button variant="outline" onClick={() => setConfirming(false)}>
                Back
              </Button>
              <Button onClick={handleConfirm} disabled={isLoading} data-testid="confirm-adjust">
                {isLoading ? "Saving…" : "Confirm"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
