"use client";

import { useState } from "react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
  useSortable,
  arrayMove,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { GripVertical } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/src/lib/api-client";
import type { WorkOrder } from "./types";

interface SortableItemProps {
  wo: WorkOrder;
}

function SortableItem({ wo }: SortableItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: wo.id });

  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      // `bg-card` rather than a hard-coded white, so these rows are legible in the default dark
      // theme — same fix as WorkOrderList.
      className="flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm shadow-sm"
    >
      <Button
        variant="ghost"
        size="icon-sm"
        {...attributes}
        {...listeners}
        className="cursor-grab text-muted-foreground hover:text-foreground"
        aria-label="Drag to reorder"
      >
        <GripVertical className="h-4 w-4" />
      </Button>
      <span className="font-mono text-xs text-muted-foreground">
        {wo.wo_number}
      </span>
      <span>{wo.product}</span>
    </div>
  );
}

interface PriorityReorderProps {
  workOrders: WorkOrder[];
  onReordered?: (updated: WorkOrder[]) => void;
}

export function PriorityReorder({
  workOrders,
  onReordered,
}: PriorityReorderProps) {
  const [items, setItems] = useState(workOrders);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const oldIdx = items.findIndex((wo) => wo.id === active.id);
    const newIdx = items.findIndex((wo) => wo.id === over.id);
    const reordered = arrayMove(items, oldIdx, newIdx);
    const previousItems = items;
    setItems(reordered);
    onReordered?.(reordered);

    const movedWo = reordered[newIdx];
    await apiClient
      .patch(`/work-orders/${movedWo.id}/sequence`, {
        display_sequence: newIdx,
      })
      .catch(() => setItems(previousItems));
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext
        items={items.map((wo) => wo.id)}
        strategy={verticalListSortingStrategy}
      >
        <div className="space-y-1">
          {items.map((wo) => (
            <SortableItem key={wo.id} wo={wo} />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
}
