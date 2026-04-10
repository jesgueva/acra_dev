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
import { apiClient } from "@/src/lib/api-client";
import { InventoryItem } from "./types";

interface AdjustQuantityModalProps {
  item: InventoryItem | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function AdjustQuantityModal({
  item,
  onClose,
  onSuccess,
}: AdjustQuantityModalProps) {
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const open = item !== null;

  const handleClose = () => {
    setQuantity("");
    setReason("");
    setConfirming(false);
    setError(null);
    onClose();
  };

  const handleSubmit = () => {
    setError(null);
    const qty = Number(quantity);
    if (isNaN(qty) || qty < 0) {
      setError("Quantity must be a non-negative number.");
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
        quantity_on_hand: Number(quantity),
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

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) handleClose(); }}>
      <DialogContent data-testid="adjust-modal">
        <DialogHeader>
          <DialogTitle>Adjust Quantity — {item?.item_name}</DialogTitle>
          <DialogDescription>
            Enter the new quantity and a reason for this adjustment.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <p className="text-sm text-destructive" data-testid="adjust-error">
            {error}
          </p>
        )}

        {!confirming ? (
          <div className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="new-quantity">New Quantity</Label>
              <Input
                id="new-quantity"
                type="number"
                min="0"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
                placeholder="Enter new quantity"
                data-testid="quantity-input"
              />
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
              Set <strong>{item?.item_name}</strong> quantity to{" "}
              <strong>{quantity}</strong>?
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
