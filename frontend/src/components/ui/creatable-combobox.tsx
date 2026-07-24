"use client";

import * as React from "react";
import { Combobox, type ComboboxOption } from "@/components/ui/combobox";

export interface CreatableItem {
  id: number;
  label: string;
}

export interface CreatableComboboxProps {
  items: CreatableItem[];
  value: number | null;
  pendingLabel: string | null;
  onSelect: (id: number) => void;
  onCreate: (label: string) => void;
  onClear?: () => void;
  placeholder?: string;
  createLabel?: (query: string) => string;
  noResultsText?: string;
  disabled?: boolean;
  highlighted?: boolean;
  className?: string;
}

const CREATE_PREFIX = "__create__:";

export function CreatableCombobox({
  items,
  value,
  pendingLabel,
  onSelect,
  onCreate,
  placeholder,
  createLabel = (q) => `Create "${q}"`,
  noResultsText,
  disabled = false,
  highlighted = false,
  className,
}: CreatableComboboxProps) {
  const selectedItem = value != null ? items.find((i) => i.id === value) : null;

  const initialQuery = selectedItem
    ? selectedItem.label
    : pendingLabel ?? "";

  const [query, setQuery] = React.useState(initialQuery);

  // Re-seed query when external state changes (e.g. OCR pre-fill)
  React.useEffect(() => {
    if (selectedItem) {
      setQuery(selectedItem.label);
    } else if (pendingLabel) {
      setQuery(pendingLabel);
    }
  }, [value, pendingLabel, selectedItem]);

  const lowerQuery = query.toLowerCase();

  const filtered = items.filter((i) =>
    i.label.toLowerCase().includes(lowerQuery)
  );

  const exactMatch = items.some(
    (i) => i.label.toLowerCase() === lowerQuery
  );

  const options: ComboboxOption[] = filtered.map((i) => ({
    value: String(i.id),
    label: i.label,
  }));

  if (query.trim() && !exactMatch) {
    options.push({
      value: `${CREATE_PREFIX}${query.trim()}`,
      label: createLabel(query.trim()),
      isCreate: true,
    });
  }

  const comboValue = selectedItem ? String(selectedItem.id) : "";

  function handleSelect(val: string) {
    if (val.startsWith(CREATE_PREFIX)) {
      const name = val.slice(CREATE_PREFIX.length);
      onCreate(name);
    } else {
      const id = Number(val);
      onSelect(id);
      const found = items.find((i) => i.id === id);
      if (found) setQuery(found.label);
    }
  }

  return (
    <Combobox
      options={options}
      value={comboValue}
      onSelect={handleSelect}
      placeholder={placeholder}
      displayValue={!selectedItem && pendingLabel ? pendingLabel : undefined}
      emptyText={noResultsText}
      disabled={disabled}
      highlighted={highlighted}
      className={className}
      inputValue={query}
      onInputChange={setQuery}
    />
  );
}
