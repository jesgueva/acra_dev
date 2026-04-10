import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { Inventory } from "../Inventory";
import { AuthContextValue } from "@/src/contexts/AuthContext";
import { ROLES } from "@/src/lib/privileges";

// ── Module mocks ──────────────────────────────────────────────────────────────

jest.mock("@/src/contexts/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@tanstack/react-query", () => ({
  useQuery: jest.fn(),
  useQueryClient: jest.fn(() => ({ invalidateQueries: jest.fn() })),
  QueryClient: jest.fn(),
  QueryClientProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock("@/src/lib/api-client", () => ({
  apiClient: {
    get: jest.fn(),
    patch: jest.fn(),
  },
}));

jest.mock("recharts", () => ({
  BarChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="bar-chart">{children}</div>
  ),
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  ReferenceLine: () => null,
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

// ── Imports after mocks ───────────────────────────────────────────────────────

import { useAuth } from "@/src/contexts/AuthContext";
import { useQuery } from "@tanstack/react-query";

// ── Helpers ───────────────────────────────────────────────────────────────────

const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;
const mockUseQuery = useQuery as jest.MockedFunction<typeof useQuery>;

function makeAuth(roles: string[]): AuthContextValue {
  return {
    user: {
      user_id: 1,
      full_name: "Test User",
      roles,
      preferred_language: "en",
      effective_privileges: [],
    },
    token: "test-token",
    isAuthenticated: true,
    authResolved: true,
    login: jest.fn(),
    logout: jest.fn(),
    hasPrivilege: jest.fn(() => false),
  };
}

const SAMPLE_ITEMS = [
  {
    id: 1,
    material_type: "Steel Rod",
    category: "raw",
    lot_batch_number: "LOT-001",
    quantity_on_hand: 150,
    storage_location: "RACK-A",
    last_updated: "2026-04-01T10:00:00Z",
    is_triggered: false,
  },
  {
    id: 2,
    material_type: "Copper Wire",
    category: "finished",
    lot_batch_number: "LOT-002",
    quantity_on_hand: 5,
    storage_location: "RACK-B",
    last_updated: "2026-04-02T10:00:00Z",
    is_triggered: true,
  },
];

// Routes useQuery calls by queryKey[0] so mocks stay stable across re-renders.
function setupInventoryQuery(items = SAMPLE_ITEMS, traceData?: object) {
  mockUseQuery.mockImplementation((options: Parameters<typeof useQuery>[0]) => {
    const key = (options.queryKey as string[])[0];
    if (key === "inventory") {
      return {
        data: { results: items, total: items.length, page: 1, page_size: 50 },
        isLoading: false,
        error: null,
      } as ReturnType<typeof useQuery>;
    }
    if (key === "traceability") {
      return {
        data: traceData ?? undefined,
        isLoading: traceData === undefined,
        error: null,
      } as ReturnType<typeof useQuery>;
    }
    return { data: undefined, isLoading: false, error: null } as ReturnType<typeof useQuery>;
  });
}

beforeEach(() => {
  jest.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

test("renders inventory table with items", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.SUPERVISOR]));
  setupInventoryQuery();

  render(<Inventory />);

  expect(screen.getByTestId("inventory-table")).toBeInTheDocument();
  expect(screen.getByText("Steel Rod")).toBeInTheDocument();
  expect(screen.getByText("Copper Wire")).toBeInTheDocument();
});

test("shows red low-stock badge when is_triggered is true", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.SUPERVISOR]));
  setupInventoryQuery();

  render(<Inventory />);

  expect(screen.getByTestId("low-stock-badge-2")).toBeInTheDocument();
  expect(screen.getByTestId("low-stock-badge-2")).toHaveTextContent("Low Stock");
  expect(screen.queryByTestId("low-stock-badge-1")).not.toBeInTheDocument();
});

test("opens TraceabilityView dialog when row is clicked", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.SUPERVISOR]));
  setupInventoryQuery();

  render(<Inventory />);
  fireEvent.click(screen.getByTestId("row-1"));

  expect(screen.getByTestId("traceability-dialog")).toBeInTheDocument();
  expect(screen.getByText(/Traceability — LOT-001/)).toBeInTheDocument();
});

test("admin sees Adjust button; clicking opens AdjustQuantityModal", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.ADMIN]));
  setupInventoryQuery();

  render(<Inventory />);

  const adjustBtn = screen.getByTestId("adjust-btn-1");
  expect(adjustBtn).toBeInTheDocument();

  fireEvent.click(adjustBtn);
  expect(screen.getByTestId("adjust-modal")).toBeInTheDocument();
  expect(screen.getByText(/Adjust Quantity — Steel Rod/)).toBeInTheDocument();
});

test("non-admin user does not see Adjust button", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.CLERK]));
  setupInventoryQuery();

  render(<Inventory />);

  expect(screen.queryByTestId("adjust-btn-1")).not.toBeInTheDocument();
});

test("AdjustQuantityModal shows inline error for negative quantity", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.ADMIN]));
  setupInventoryQuery();

  render(<Inventory />);

  fireEvent.click(screen.getByTestId("adjust-btn-1"));

  const quantityInput = screen.getByTestId("quantity-input");
  fireEvent.change(quantityInput, { target: { value: "-5" } });
  fireEvent.click(screen.getByText("Review"));

  expect(screen.getByTestId("adjust-error")).toHaveTextContent(
    "Quantity must be a non-negative number."
  );
});

test("FilterPanel Clear Filters button resets all filter state", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.SUPERVISOR]));
  setupInventoryQuery();

  render(<Inventory />);

  fireEvent.click(screen.getByTestId("category-raw"));
  fireEvent.click(screen.getByTestId("clear-filters"));

  expect(screen.getByTestId("category-all")).toBeInTheDocument();
});

test("admin sees InventoryTrendLine bar chart when items are present", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.ADMIN]));
  setupInventoryQuery();

  render(<Inventory />);

  expect(screen.getByTestId("bar-chart")).toBeInTheDocument();
});
