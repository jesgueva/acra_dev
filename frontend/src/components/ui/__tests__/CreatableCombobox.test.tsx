import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreatableCombobox } from "../creatable-combobox";

const ITEMS = [
  { id: 1, label: "Alpha Freight" },
  { id: 2, label: "Beta Logistics" },
  { id: 3, label: "Gamma Transport" },
];

const baseProps = {
  items: ITEMS,
  value: null,
  pendingLabel: null,
  onSelect: jest.fn(),
  onCreate: jest.fn(),
};

afterEach(() => jest.clearAllMocks());

test("1: renders placeholder when no value", () => {
  render(<CreatableCombobox {...baseProps} placeholder="Select carrier…" />);
  expect(screen.getByRole("combobox")).toHaveTextContent("Select carrier…");
});

test("2: shows selected item label when value matches an id", () => {
  render(<CreatableCombobox {...baseProps} value={2} />);
  expect(screen.getByRole("combobox")).toHaveTextContent("Beta Logistics");
});

test("3: seeds input with pendingLabel when no id match", async () => {
  render(
    <CreatableCombobox {...baseProps} pendingLabel="New Carrier" placeholder="Select…" />
  );
  await userEvent.click(screen.getByRole("combobox"));
  const input = await screen.findByPlaceholderText("Select…");
  expect(input).toHaveValue("New Carrier");
});

test("4: filters items as user types", async () => {
  render(<CreatableCombobox {...baseProps} placeholder="Search…" />);
  await userEvent.click(screen.getByRole("combobox"));
  const input = await screen.findByPlaceholderText("Search…");
  await userEvent.clear(input);
  await userEvent.type(input, "Beta");
  expect(screen.getByText("Beta Logistics")).toBeInTheDocument();
  expect(screen.queryByText("Alpha Freight")).not.toBeInTheDocument();
});

test("5: calls onSelect(id) when an existing item is picked", async () => {
  const onSelect = jest.fn();
  render(<CreatableCombobox {...baseProps} onSelect={onSelect} />);
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(await screen.findByText("Alpha Freight"));
  expect(onSelect).toHaveBeenCalledWith(1);
});

test("6: shows 'Create' option when query matches nothing", async () => {
  render(
    <CreatableCombobox
      {...baseProps}
      placeholder="Search…"
      createLabel={(q) => `Create "${q}"`}
    />
  );
  await userEvent.click(screen.getByRole("combobox"));
  const input = await screen.findByPlaceholderText("Search…");
  await userEvent.clear(input);
  await userEvent.type(input, "Unknown Carrier");
  expect(screen.getByText('Create "Unknown Carrier"')).toBeInTheDocument();
});

test("7: calls onCreate(query) when the Create option is picked", async () => {
  const onCreate = jest.fn();
  render(
    <CreatableCombobox
      {...baseProps}
      onCreate={onCreate}
      placeholder="Search…"
      createLabel={(q) => `Create "${q}"`}
    />
  );
  await userEvent.click(screen.getByRole("combobox"));
  const input = await screen.findByPlaceholderText("Search…");
  await userEvent.clear(input);
  await userEvent.type(input, "New Carrier");
  await userEvent.click(screen.getByText('Create "New Carrier"'));
  expect(onCreate).toHaveBeenCalledWith("New Carrier");
});

test("8: does not show Create option when query exactly matches an existing item", async () => {
  render(
    <CreatableCombobox
      {...baseProps}
      placeholder="Search…"
      createLabel={(q) => `Create "${q}"`}
    />
  );
  await userEvent.click(screen.getByRole("combobox"));
  const input = await screen.findByPlaceholderText("Search…");
  await userEvent.clear(input);
  await userEvent.type(input, "Alpha Freight");
  expect(screen.queryByText('Create "Alpha Freight"')).not.toBeInTheDocument();
});

test("9: renders disabled and blocks interaction", async () => {
  render(<CreatableCombobox {...baseProps} disabled />);
  const button = screen.getByRole("combobox");
  expect(button).toBeDisabled();
});
