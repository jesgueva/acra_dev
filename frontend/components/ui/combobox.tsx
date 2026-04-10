"use client";

import * as React from "react";
import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

export interface ComboboxOption {
  value: string;
  label: string;
  isCreate?: boolean;
}

export interface ComboboxProps {
  options: ComboboxOption[];
  value: string;
  onSelect: (value: string) => void;
  placeholder?: string;
  /** Shown in the trigger button when no item is selected (e.g. OCR pending name) */
  displayValue?: string;
  emptyText?: string;
  disabled?: boolean;
  className?: string;
  highlighted?: boolean;
  inputValue?: string;
  onInputChange?: (value: string) => void;
}

export function Combobox({
  options,
  value,
  onSelect,
  placeholder = "Select…",
  displayValue,
  emptyText,
  disabled = false,
  className,
  highlighted = false,
  inputValue,
  onInputChange,
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false);

  const selected = options.find((o) => !o.isCreate && o.value === value);
  const triggerLabel = selected?.label ?? displayValue;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn(
            "w-full justify-between font-normal",
            !triggerLabel && "text-muted-foreground",
            highlighted && "border-yellow-400 bg-yellow-50/10",
            className
          )}
        >
          <span className="truncate">{triggerLabel ?? placeholder}</span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
        <Command shouldFilter={false}>
          <CommandInput
            placeholder={placeholder}
            value={inputValue}
            onValueChange={onInputChange}
          />
          <CommandList>
            {emptyText && <CommandEmpty>{emptyText}</CommandEmpty>}
            <CommandGroup>
              {options.map((option) => (
                <CommandItem
                  key={option.value}
                  value={option.value}
                  onSelect={(currentValue) => {
                    onSelect(currentValue);
                    setOpen(false);
                  }}
                  className={option.isCreate ? "text-amber-600 dark:text-amber-400" : ""}
                >
                  {option.isCreate ? (
                    <Plus className="mr-2 h-4 w-4" />
                  ) : (
                    <Check
                      className={cn(
                        "mr-2 h-4 w-4",
                        value === option.value ? "opacity-100" : "opacity-0"
                      )}
                    />
                  )}
                  {option.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
