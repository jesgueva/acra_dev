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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiClient } from "@/src/lib/api-client";
import { errorDetailText } from "@/src/lib/api-error";
import type { MaterialAvailability, WorkOrderCreateResponse } from "./types";

interface MaterialRow {
  material_type: string;
  quantity_required: string;
}

interface CreateWorkOrderFormProps {
  open: boolean;
  onClose: () => void;
  onCreated?: () => void;
}

export function CreateWorkOrderForm({
  open,
  onClose,
  onCreated,
}: CreateWorkOrderFormProps) {
  const [product, setProduct] = useState("");
  const [quantity, setQuantity] = useState("");
  const [priority, setPriority] = useState("medium");
  const [targetDate, setTargetDate] = useState("");
  const [productionLine, setProductionLine] = useState("");
  const [materials, setMaterials] = useState<MaterialRow[]>([
    { material_type: "", quantity_required: "" },
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [availability, setAvailability] = useState<MaterialAvailability[] | null>(null);

  const addMaterialRow = () =>
    setMaterials((prev) => [
      ...prev,
      { material_type: "", quantity_required: "" },
    ]);

  const updateMaterial = (
    idx: number,
    field: keyof MaterialRow,
    value: string
  ) =>
    setMaterials((prev) =>
      prev.map((row, i) => (i === idx ? { ...row, [field]: value } : row))
    );

  const handleSubmit = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const res = await apiClient.post<WorkOrderCreateResponse>("/work-orders", {
        product,
        quantity_required: parseFloat(quantity),
        priority,
        target_date: targetDate,
        production_line: productionLine || undefined,
        materials: materials
          .filter((m) => m.material_type && m.quantity_required)
          .map((m) => ({
            material_type: m.material_type,
            quantity_required: parseFloat(m.quantity_required),
          })),
      });
      setAvailability(res.data.material_availability);
      onCreated?.();
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        setError(errorDetailText(err, "Failed to create work order."));
      } else {
        setError("Failed to create work order.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = () => {
    setProduct("");
    setQuantity("");
    setPriority("medium");
    setTargetDate("");
    setProductionLine("");
    setMaterials([{ material_type: "", quantity_required: "" }]);
    setError(null);
    setAvailability(null);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create Work Order</DialogTitle>
        </DialogHeader>

        {availability ? (
          <div className="space-y-3 py-2">
            <p className="text-sm font-medium">Material Availability</p>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Material</TableHead>
                  <TableHead>Required</TableHead>
                  <TableHead>Available</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {availability.map((item) => (
                  <TableRow key={item.material_type}>
                    <TableCell>{item.material_type}</TableCell>
                    <TableCell>{item.required}</TableCell>
                    <TableCell>{item.available}</TableCell>
                    <TableCell>
                      <span
                        data-testid={`avail-${item.material_type}`}
                        className={
                          item.sufficient ? "text-green-600" : "text-red-600"
                        }
                      >
                        {item.sufficient ? "Sufficient" : "Insufficient"}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <DialogFooter>
              <Button onClick={handleClose}>Done</Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4 py-2">
            <div className="space-y-1">
              <Label htmlFor="wo-product">Product</Label>
              <Input
                id="wo-product"
                value={product}
                onChange={(e) => setProduct(e.target.value)}
                placeholder="Product name"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <Label htmlFor="wo-qty">Quantity</Label>
                <Input
                  id="wo-qty"
                  type="number"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                  placeholder="0"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="wo-date">Target Date</Label>
                <Input
                  id="wo-date"
                  type="date"
                  value={targetDate}
                  onChange={(e) => setTargetDate(e.target.value)}
                />
              </div>
            </div>

            <div className="space-y-1">
              <Label>Priority</Label>
              <Select value={priority} onValueChange={setPriority}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {["low", "medium", "high", "urgent"].map((p) => (
                    <SelectItem key={p} value={p}>
                      {p.charAt(0).toUpperCase() + p.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Materials</Label>
              {materials.map((row, idx) => (
                <div key={idx} className="flex gap-2">
                  <Input
                    placeholder="Material type"
                    value={row.material_type}
                    onChange={(e) =>
                      updateMaterial(idx, "material_type", e.target.value)
                    }
                  />
                  <Input
                    placeholder="Qty"
                    type="number"
                    value={row.quantity_required}
                    onChange={(e) =>
                      updateMaterial(idx, "quantity_required", e.target.value)
                    }
                    className="w-24"
                  />
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={addMaterialRow}
              >
                Add Material
              </Button>
            </div>

            {error && (
              <p role="alert" className="text-sm text-red-600">
                {error}
              </p>
            )}

            <DialogFooter>
              <Button variant="outline" onClick={handleClose} disabled={isLoading}>
                Cancel
              </Button>
              <Button onClick={handleSubmit} disabled={isLoading}>
                {isLoading ? "Creating…" : "Create"}
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
