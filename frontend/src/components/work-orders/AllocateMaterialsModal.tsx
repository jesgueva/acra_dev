"use client";

import { useState } from "react";
import axios from "axios";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/src/lib/api-client";

interface AllocateMaterialsModalProps {
  open: boolean;
  workOrderId: number;
  onClose: () => void;
  onSuccess: () => void;
}

export function AllocateMaterialsModal({
  open,
  workOrderId,
  onClose,
  onSuccess,
}: AllocateMaterialsModalProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAllocate = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await apiClient.patch(`/work-orders/${workOrderId}/allocate`);
      onSuccess();
      onClose();
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.status === 409) {
        setError(err.response.data?.detail ?? "Insufficient stock");
      } else {
        setError("Allocation failed. Please try again.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setError(null);
      onClose();
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Allocate Materials</DialogTitle>
        </DialogHeader>

        <div className="space-y-3 py-2">
          <p
            role="note"
            className="rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2 text-sm text-yellow-800"
          >
            Warning: Materials may be insufficient. Allocation will deduct from
            inventory using FIFO order.
          </p>

          {error && (
            <p role="alert" className="text-sm text-red-600">
              {error}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button onClick={handleAllocate} disabled={isLoading}>
            {isLoading ? "Allocating…" : "Allocate"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
