"use client";

import { useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiClient } from "@/src/lib/api-client";

const PRODUCTION_LINES = ["Line 1", "Line 2", "Line 3", "Line 4"];

interface AssignLineDropdownProps {
  workOrderId: number;
  currentLine?: string | null;
  capacityWarning?: string | null;
  onAssigned: (line: string, warning?: string | null) => void;
}

export function AssignLineDropdown({
  workOrderId,
  currentLine,
  capacityWarning,
  onAssigned,
}: AssignLineDropdownProps) {
  const [selectedLine, setSelectedLine] = useState(currentLine ?? "");
  const [isLoading, setIsLoading] = useState(false);

  const handleSelect = async (line: string) => {
    setSelectedLine(line);
    setIsLoading(true);
    try {
      const res = await apiClient.patch<{
        production_line: string;
        capacity_warning?: string | null;
      }>(`/work-orders/${workOrderId}/assign`, { production_line: line });
      onAssigned(res.data.production_line, res.data.capacity_warning);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-2">
      <Select
        value={selectedLine || undefined}
        onValueChange={handleSelect}
        disabled={isLoading}
      >
        <SelectTrigger className="w-48">
          <SelectValue placeholder="Assign production line" />
        </SelectTrigger>
        <SelectContent>
          {PRODUCTION_LINES.map((line) => (
            <SelectItem key={line} value={line}>
              {line}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {capacityWarning && (
        <div
          role="status"
          className="rounded-md border border-yellow-300 bg-yellow-50 px-3 py-2 text-sm text-yellow-800"
          data-testid="capacity-warning"
        >
          {capacityWarning}
        </div>
      )}
    </div>
  );
}
