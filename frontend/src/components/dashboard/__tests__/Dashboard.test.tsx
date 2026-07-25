import React from "react";
import { render, screen } from "@testing-library/react";
import { Dashboard } from "../Dashboard";
import { AuthContextValue } from "@/src/contexts/AuthContext";
import { ROLES } from "@/src/lib/privileges";

// ── Module mocks ──────────────────────────────────────────────────────────────

jest.mock("@/src/contexts/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@tanstack/react-query", () => ({
  useQuery: jest.fn(),
  QueryClient: jest.fn(),
  QueryClientProvider: ({ children }: { children: React.ReactNode }) =>
    children,
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

// useQuery is called 4 times in Dashboard, in this order: alerts, deliveries, work-orders, users.
// The inventory chart is derived from the alerts payload rather than fetched separately, because
// alerts is the only endpoint that carries `threshold`.
function setupQueries({
  alerts = [],
  deliveryCount = 0,
  workOrderCount = 0,
  userCount = 0,
}: {
  alerts?: object[];
  deliveryCount?: number;
  workOrderCount?: number;
  userCount?: number;
} = {}) {
  mockUseQuery
    .mockReturnValueOnce({ data: alerts, isLoading: false, error: null } as ReturnType<typeof useQuery>)
    .mockReturnValueOnce({ data: deliveryCount, isLoading: false, error: null } as ReturnType<typeof useQuery>)
    .mockReturnValueOnce({ data: workOrderCount, isLoading: false, error: null } as ReturnType<typeof useQuery>)
    .mockReturnValueOnce({ data: userCount, isLoading: false, error: null } as ReturnType<typeof useQuery>);
}

/** An alert row exactly as `GET /inventory/alerts` returns it. */
function alertRow(overrides: Partial<{
  id: number; product_id: number; product_name: string;
  current_quantity: number; threshold: number; is_triggered: boolean;
}> = {}) {
  return {
    id: 1,
    product_id: 1,
    product_name: "Steel",
    current_quantity: 5,
    threshold: 10,
    is_triggered: true,
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

test("renders admin summary cards for admin user", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.ADMIN]));
  setupQueries({ deliveryCount: 42, workOrderCount: 7, userCount: 10 });

  render(<Dashboard />);

  expect(screen.getByText("Total Deliveries")).toBeInTheDocument();
  expect(screen.getByText("42")).toBeInTheDocument();
  expect(screen.getByText("Active Work Orders")).toBeInTheDocument();
  expect(screen.getByText("Low Stock Items")).toBeInTheDocument();
  expect(screen.getByText("Active Users")).toBeInTheDocument();
});

test("shows alert banner when low-stock alerts are triggered (admin)", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.ADMIN]));
  setupQueries({
    alerts: [
      alertRow({ product_name: "Steel" }),
      alertRow({ id: 2, product_id: 2, product_name: "Copper", current_quantity: 2, threshold: 8 }),
    ],
  });

  render(<Dashboard />);

  expect(screen.getByRole("alert")).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("Low Stock Alert");
  expect(screen.getByRole("alert")).toHaveTextContent("Steel");
});

test("hides alert banner for non-admin users", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.SUPERVISOR]));
  setupQueries({
    alerts: [alertRow()],
  });

  render(<Dashboard />);

  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("renders inventory level chart for admin", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.ADMIN]));
  setupQueries({
    alerts: [
      alertRow({ product_name: "Steel", current_quantity: 100, threshold: 20 }),
      alertRow({ id: 2, product_id: 2, product_name: "Copper", current_quantity: 50, threshold: 10 }),
    ],
  });

  render(<Dashboard />);

  expect(screen.getByTestId("bar-chart")).toBeInTheDocument();
});

test("does not render inventory level chart for clerk", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.CLERK]));
  setupQueries({ deliveryCount: 3 });

  render(<Dashboard />);

  expect(screen.queryByTestId("bar-chart")).not.toBeInTheDocument();
  expect(screen.getByText("Deliveries Today")).toBeInTheDocument();
});

test("renders role-specific quick action links", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.CLERK]));
  setupQueries({ deliveryCount: 1 });

  render(<Dashboard />);

  const nav = screen.getByRole("navigation", { name: "Quick actions" });
  expect(nav).toBeInTheDocument();
  expect(nav).toHaveTextContent("Receiving");
  expect(nav).not.toHaveTextContent("Users");
  expect(nav).not.toHaveTextContent("Audit Log");
});

// ── Regression: the alerts queryFn (ACR-21) ──────────────────────────────────
// The tests above mock useQuery wholesale, so the real queryFn never ran — which is exactly how
// `GET /inventory/alerts` returning `{ alerts: [...] }` instead of a bare array reached production
// and crashed the dashboard with "TypeError: filter is not a function". These run it for real.

jest.mock("@/src/lib/api-client", () => ({
  apiClient: { get: jest.fn() },
}));

import { apiClient } from "@/src/lib/api-client";

const mockGet = apiClient.get as jest.MockedFunction<typeof apiClient.get>;

/** Render, then pull the queryFn the component handed to the first useQuery call (alerts). */
async function runAlertsQueryFn() {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.ADMIN]));
  setupQueries();
  render(<Dashboard />);

  const options = mockUseQuery.mock.calls[0][0] as { queryFn: () => Promise<unknown> };
  return options.queryFn();
}

test("the alerts query unwraps the API's { alerts: [...] } envelope", async () => {
  const row = alertRow();
  mockGet.mockResolvedValueOnce({ data: { alerts: [row] } } as never);

  await expect(runAlertsQueryFn()).resolves.toEqual([row]);
  expect(mockGet).toHaveBeenCalledWith("/inventory/alerts");
});

test("the alerts query yields an array when the envelope is empty", async () => {
  mockGet.mockResolvedValueOnce({ data: {} } as never);

  // Must be an array: the caller does `alerts.filter(...)` and `alerts.map(...)` unconditionally.
  await expect(runAlertsQueryFn()).resolves.toEqual([]);
});

test("the chart is built from the alert rows, carrying their thresholds", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.ADMIN]));
  setupQueries({
    alerts: [alertRow({ product_name: "Steel", current_quantity: 100, threshold: 20 })],
  });

  render(<Dashboard />);

  // The previous implementation fetched `/inventory?category=raw` and read a `items` key that the
  // endpoint never returns, so the chart was permanently empty.
  expect(screen.getByTestId("bar-chart")).toBeInTheDocument();
  expect(mockUseQuery).toHaveBeenCalledTimes(4);
});
