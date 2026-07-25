"use client";

import { useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/src/contexts/AuthContext";
import { PRIVILEGES } from "@/src/lib/privileges";
import { STATUS_LABELS, STATUS_BADGE_VARIANTS } from "./constants";
import type { WorkOrder } from "./types";
import { AllocateMaterialsModal } from "./AllocateMaterialsModal";
import { AssignLineDropdown } from "./AssignLineDropdown";

const STATUS_TIMELINE: Array<{ key: string; label: string }> = [
  { key: "created", label: "Created" },
  { key: "materials_allocated", label: "Materials Allocated" },
  { key: "in_production", label: "In Production" },
  { key: "completed", label: "Completed" },
];

interface WorkOrderDetailProps {
  workOrder: WorkOrder;
  onClose: () => void;
  onUpdated?: () => void;
}

export function WorkOrderDetail({
  workOrder,
  onClose,
  onUpdated,
}: WorkOrderDetailProps) {
  const { hasPrivilege } = useAuth();
  const [allocateOpen, setAllocateOpen] = useState(false);
  const [capacityWarning, setCapacityWarning] = useState<string | null>(null);

  const canAllocate = hasPrivilege(PRIVILEGES.WORK_ORDERS_ALLOCATE);
  const canAssign = hasPrivilege(PRIVILEGES.WORK_ORDERS_ASSIGN);
  const showAllocate = workOrder.status === "created" && canAllocate;

  const currentStepIdx = STATUS_TIMELINE.findIndex(
    (s) => s.key === workOrder.status
  );

  return (
    <>
      <Sheet open onOpenChange={(o) => !o && onClose()}>
        <SheetContent className="w-full sm:max-w-xl overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{workOrder.wo_number}</SheetTitle>
          </SheetHeader>

          <div className="mt-4 space-y-6">
            <div className="flex flex-wrap gap-2">
              <Badge variant={STATUS_BADGE_VARIANTS[workOrder.status] ?? "outline"}>
                {STATUS_LABELS[workOrder.status] ?? workOrder.status}
              </Badge>
              <Badge variant="outline">{workOrder.priority}</Badge>
            </div>

            <div className="grid grid-cols-2 gap-2 text-sm">
              <div>
                <p className="text-muted-foreground">Product</p>
                <p className="font-medium">{workOrder.product}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Target Date</p>
                <p className="font-medium">{workOrder.target_date}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Qty Required</p>
                <p className="font-medium">{workOrder.quantity_required}</p>
              </div>
              <div>
                <p className="text-muted-foreground">Qty Produced</p>
                <p className="font-medium">{workOrder.quantity_produced}</p>
              </div>
            </div>

            <Separator />

            <div>
              <p className="mb-2 text-sm font-medium">Progress</p>
              <ol className="flex gap-4">
                {STATUS_TIMELINE.map((step, idx) => (
                  <li key={step.key} className="flex items-center gap-1 text-xs">
                    <span
                      className={
                        idx <= currentStepIdx
                          ? "font-semibold text-primary"
                          : "text-muted-foreground"
                      }
                    >
                      {step.label}
                    </span>
                    {idx < STATUS_TIMELINE.length - 1 && (
                      <span className="text-muted-foreground">→</span>
                    )}
                  </li>
                ))}
              </ol>
            </div>

            <Separator />

            <div>
              <p className="mb-2 text-sm font-medium">Materials</p>
              {workOrder.materials.length === 0 ? (
                <p className="text-sm text-muted-foreground">No materials.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Material</TableHead>
                      <TableHead>Required</TableHead>
                      <TableHead>Allocated</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {workOrder.materials.map((mat) => (
                      <TableRow key={mat.id}>
                        <TableCell>{mat.material_type}</TableCell>
                        <TableCell>{mat.quantity_required}</TableCell>
                        <TableCell>{mat.quantity_allocated}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>

            <Separator />

            <div className="space-y-4">
              {showAllocate && (
                <Button onClick={() => setAllocateOpen(true)}>
                  Allocate Materials
                </Button>
              )}

              {canAssign && (
                <div>
                  <p className="mb-1 text-sm font-medium">Assign Production Line</p>
                  <AssignLineDropdown
                    workOrderId={workOrder.id}
                    currentLine={workOrder.production_line}
                    capacityWarning={capacityWarning}
                    onAssigned={(_, warning) =>
                      setCapacityWarning(warning ?? null)
                    }
                  />
                </div>
              )}
            </div>
          </div>
        </SheetContent>
      </Sheet>

      {/* Always rendered so Dialog manages its own open state and Radix portals correctly */}
      <AllocateMaterialsModal
        open={allocateOpen}
        workOrderId={workOrder.id}
        onClose={() => setAllocateOpen(false)}
        onSuccess={() => {
          setAllocateOpen(false);
          onUpdated?.();
        }}
      />
    </>
  );
}
