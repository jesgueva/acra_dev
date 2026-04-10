"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DEFAULT_FILTERS, FilterState } from "./types";

interface FilterPanelProps {
  filters: FilterState;
  onChange: (filters: FilterState) => void;
}

const ALL_SENTINEL = "__all__";

const STATUSES = [
  { value: ALL_SENTINEL, label: "All" },
  { value: "in_storage", label: "In Storage" },
  { value: "in_production", label: "In Production" },
  { value: "shipped", label: "Shipped" },
  { value: "consumed", label: "Consumed" },
];

export function FilterPanel({ filters, onChange }: FilterPanelProps) {
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [search, setSearch] = useState(filters.search);
  const [prevSearch, setPrevSearch] = useState(filters.search);

  if (prevSearch !== filters.search) {
    setPrevSearch(filters.search);
    setSearch(filters.search);
  }

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearch(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        onChange({ ...filters, search: value });
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
      <Select
        value={filters.status === "" ? ALL_SENTINEL : filters.status}
        onValueChange={(value) =>
          onChange({ ...filters, status: value === ALL_SENTINEL ? "" : value })
        }
      >
        <SelectTrigger className="w-44" data-testid="status-select">
          <SelectValue placeholder="All statuses" />
        </SelectTrigger>
        <SelectContent>
          {STATUSES.map(({ value, label }) => (
            <SelectItem key={value} value={value}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Input
        placeholder="Search product or location…"
        value={search}
        onChange={(e) => handleSearchChange(e.target.value)}
        className="w-72"
        data-testid="search-input"
      />

      <Button variant="ghost" size="sm" onClick={handleClear} data-testid="clear-filters">
        Clear Filters
      </Button>
    </div>
  );
}
