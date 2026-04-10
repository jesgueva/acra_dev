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

interface SplitLotModalProps {
  lot: InventoryLot | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function SplitLotModal({ lot, onClose, onSuccess }: SplitLotModalProps) {
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
      setError("Enter a valid positive quantity to split off.");
      return;
    }
    if (qty > lot.quantity_on_hand) {
      setError(
        `Split quantity (${toDisplay(qty)}) exceeds lot quantity (${toDisplay(lot.quantity_on_hand)}).`
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
      setError("Failed to split lot. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) handleClose(); }}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Split Lot — #{lot?.id}</DialogTitle>
          <DialogDescription>
            Move part of this lot to a new location. Current quantity:{" "}
            <strong>{lot ? toDisplay(lot.quantity_on_hand) : "—"}</strong>
          </DialogDescription>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="split-qty">Quantity to Split Off</Label>
            <Input
              id="split-qty"
              type="number"
              min="0.01"
              step="0.01"
              value={splitQty}
              onChange={(e) => setSplitQty(e.target.value)}
              placeholder="e.g. 50.00"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="new-location">New Location (optional)</Label>
            <Input
              id="new-location"
              value={newLocation}
              onChange={(e) => setNewLocation(e.target.value)}
              placeholder="e.g. B-02-1"
            />
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleClose}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isLoading || !splitQty}>
            {isLoading ? "Splitting…" : "Split"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
