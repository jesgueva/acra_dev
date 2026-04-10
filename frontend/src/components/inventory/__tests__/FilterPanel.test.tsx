import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FilterPanel } from "../FilterPanel";
import { DEFAULT_FILTERS, FilterState } from "../types";

// ── Mocks ─────────────────────────────────────────────────────────────────────

// Replace Radix Select with a plain <select> so we can drive interactions in
// JSDOM.  The mock must honour the sentinel-value contract (no empty string).
jest.mock("@/components/ui/select", () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string;
    onValueChange: (v: string) => void;
    children: React.ReactNode;
  }) => (
    <select
      data-testid="status-select"
      value={value}
      onChange={(e) => onValueChange(e.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({
    value,
    children,
  }: {
    value: string;
    children: React.ReactNode;
  }) => <option value={value}>{children}</option>,
}));

// ── Tests ─────────────────────────────────────────────────────────────────────

test("regression: no <SelectItem> receives an empty-string value", () => {
  // Radix throws a console.error when value="" is passed to SelectItem.
  // With our mock, option elements expose their value directly — assert none is "".
  render(<FilterPanel filters={DEFAULT_FILTERS} onChange={jest.fn()} />);

  const options = screen.getAllByRole("option");
  options.forEach((opt) => {
    expect(opt).not.toHaveValue("");
  });
});

test("selecting a non-all status calls onChange with that status value", async () => {
  const user = userEvent.setup();
  const onChange = jest.fn();

  render(<FilterPanel filters={DEFAULT_FILTERS} onChange={onChange} />);

  await user.selectOptions(screen.getByTestId("status-select"), "in_storage");

  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ status: "in_storage" })
  );
});

test("selecting 'All' option maps sentinel back to empty string in onChange", async () => {
  const user = userEvent.setup();
  const onChange = jest.fn();

  const filtersWithStatus: FilterState = { status: "in_storage", search: "" };
  render(<FilterPanel filters={filtersWithStatus} onChange={onChange} />);

  await user.selectOptions(screen.getByTestId("status-select"), "__all__");

  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ status: "" })
  );
});

test("search input debounces and calls onChange with updated search value", async () => {
  jest.useFakeTimers();
  const onChange = jest.fn();

  render(<FilterPanel filters={DEFAULT_FILTERS} onChange={onChange} />);

  const input = screen.getByTestId("search-input");
  await userEvent.setup({ delay: null }).type(input, "steel");

  expect(onChange).not.toHaveBeenCalled();

  jest.runAllTimers();

  expect(onChange).toHaveBeenCalledWith(
    expect.objectContaining({ search: "steel" })
  );

  jest.useRealTimers();
});

test("Clear Filters resets search and status to defaults", async () => {
  const user = userEvent.setup();
  const onChange = jest.fn();

  const dirtyFilters: FilterState = { status: "shipped", search: "rack-a" };
  render(<FilterPanel filters={dirtyFilters} onChange={onChange} />);

  await user.click(screen.getByTestId("clear-filters"));

  expect(onChange).toHaveBeenCalledWith(DEFAULT_FILTERS);
});
