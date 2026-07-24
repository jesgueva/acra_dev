"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
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

export function FilterPanel({ filters, onChange }: FilterPanelProps) {
  const t = useTranslations("inventory");

  const statuses = useMemo(
    () => [
      { value: ALL_SENTINEL, label: t("statusAll") },
      { value: "in_storage", label: t("status.in_storage") },
      { value: "in_production", label: t("status.in_production") },
      { value: "shipped", label: t("status.shipped") },
      { value: "consumed", label: t("status.consumed") },
    ],
    [t]
  );
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
          <SelectValue placeholder={t("allStatuses")} />
        </SelectTrigger>
        <SelectContent>
          {statuses.map(({ value, label }) => (
            <SelectItem key={value} value={value}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Input
        placeholder={t("searchPlaceholder")}
        value={search}
        onChange={(e) => handleSearchChange(e.target.value)}
        className="w-72"
        data-testid="search-input"
      />

      <Button variant="ghost" size="sm" onClick={handleClear} data-testid="clear-filters">
        {t("clearFilters")}
      </Button>
    </div>
  );
}
