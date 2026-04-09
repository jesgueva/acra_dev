"use client";

import { useCallback, useRef } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { FilterState } from "./types";

interface FilterPanelProps {
  filters: FilterState;
  onChange: (filters: FilterState) => void;
}

const CATEGORIES = ["", "raw", "component", "finished"];

export function FilterPanel({ filters, onChange }: FilterPanelProps) {
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleSearchChange = useCallback(
    (value: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        onChange({ ...filters, search: value });
      }, 300);
    },
    [filters, onChange]
  );

  const handleClear = () => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    onChange({ category: "", search: "", dateFrom: "", dateTo: "" });
  };

  return (
    <div className="flex flex-wrap gap-3 items-end">
      <div className="flex gap-1">
        {CATEGORIES.map((cat) => (
          <Button
            key={cat || "all"}
            variant={filters.category === cat ? "default" : "outline"}
            size="sm"
            onClick={() => onChange({ ...filters, category: cat })}
            data-testid={`category-${cat || "all"}`}
          >
            {cat || "All"}
          </Button>
        ))}
      </div>

      <Input
        placeholder="Search material or lot…"
        defaultValue={filters.search}
        onChange={(e) => handleSearchChange(e.target.value)}
        className="w-56"
        data-testid="search-input"
      />

      <Input
        type="date"
        value={filters.dateFrom}
        onChange={(e) => onChange({ ...filters, dateFrom: e.target.value })}
        className="w-40"
        data-testid="date-from"
      />
      <span className="text-sm text-muted-foreground self-center">to</span>
      <Input
        type="date"
        value={filters.dateTo}
        onChange={(e) => onChange({ ...filters, dateTo: e.target.value })}
        className="w-40"
        data-testid="date-to"
      />

      <Button variant="ghost" size="sm" onClick={handleClear} data-testid="clear-filters">
        Clear Filters
      </Button>
    </div>
  );
}
