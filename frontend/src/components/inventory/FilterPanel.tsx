"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { DEFAULT_FILTERS, FilterState } from "./types";

interface FilterPanelProps {
  filters: FilterState;
  onChange: (filters: FilterState) => void;
}

const CATEGORIES = ["", "raw", "finished"];

export function FilterPanel({ filters, onChange }: FilterPanelProps) {
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [materialType, setMaterialType] = useState(filters.materialType);
  const [storageLocation, setStorageLocation] = useState(filters.storageLocation);

  // Track the last prop values we acknowledged so we can sync during render
  // instead of inside an effect (getDerivedStateFromProps pattern).
  const [prevMaterialType, setPrevMaterialType] = useState(filters.materialType);
  const [prevStorageLocation, setPrevStorageLocation] = useState(filters.storageLocation);

  if (prevMaterialType !== filters.materialType) {
    setPrevMaterialType(filters.materialType);
    setMaterialType(filters.materialType);
  }
  if (prevStorageLocation !== filters.storageLocation) {
    setPrevStorageLocation(filters.storageLocation);
    setStorageLocation(filters.storageLocation);
  }

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const handleSearchChange = useCallback(
    (field: "materialType" | "storageLocation", value: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        onChange({ ...filters, [field]: value });
      }, 300);
    },
    [filters, onChange]
  );

  const handleClear = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    onChange(DEFAULT_FILTERS);
  }, [onChange]);

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
        placeholder="Search material..."
        value={materialType}
        onChange={(e) => {
          setMaterialType(e.target.value);
          handleSearchChange("materialType", e.target.value);
        }}
        className="w-56"
        data-testid="material-search-input"
      />

      <Input
        placeholder="Search location..."
        value={storageLocation}
        onChange={(e) => {
          setStorageLocation(e.target.value);
          handleSearchChange("storageLocation", e.target.value);
        }}
        className="w-48"
        data-testid="location-search-input"
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
