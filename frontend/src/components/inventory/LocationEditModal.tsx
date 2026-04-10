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
import { InventoryLot } from "./types";

interface LocationEditModalProps {
  lot: InventoryLot | null;
  onClose: () => void;
  onSuccess: () => void;
}

export function LocationEditModal({ lot, onClose, onSuccess }: LocationEditModalProps) {
  const [location, setLocation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const open = lot !== null;

  const handleOpen = (isOpen: boolean) => {
    if (isOpen && lot) setLocation(lot.storage_location ?? "");
    if (!isOpen) {
      setError(null);
      onClose();
    }
  };

  const handleSubmit = async () => {
    if (!lot) return;
    setIsLoading(true);
    setError(null);
    try {
      await apiClient.patch(`/inventory/lots/${lot.id}/location`, {
        storage_location: location,
      });
      onSuccess();
      onClose();
    } catch {
      setError("Failed to update location. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit Location — Lot #{lot?.id}</DialogTitle>
          <DialogDescription>
            Update the storage location for this lot. A move transaction will be recorded.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-2">
          <Label htmlFor="location">Storage Location</Label>
          <Input
            id="location"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="e.g. A-12-3"
          />
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isLoading || !location.trim()}>
            {isLoading ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
