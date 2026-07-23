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

// useQuery is called up to 5 times in Dashboard (alerts, inventory, deliveries,
// work-orders, users). Return sensible defaults for each call.
function setupQueries({
  alerts = [],
  inventoryItems = [],
  deliveryCount = 0,
  workOrderCount = 0,
  userCount = 0,
}: {
  alerts?: object[];
  inventoryItems?: object[];
  deliveryCount?: number;
  workOrderCount?: number;
  userCount?: number;
} = {}) {
  mockUseQuery
    .mockReturnValueOnce({ data: alerts, isLoading: false, error: null } as ReturnType<typeof useQuery>)
    .mockReturnValueOnce({ data: inventoryItems, isLoading: false, error: null } as ReturnType<typeof useQuery>)
    .mockReturnValueOnce({ data: deliveryCount, isLoading: false, error: null } as ReturnType<typeof useQuery>)
    .mockReturnValueOnce({ data: workOrderCount, isLoading: false, error: null } as ReturnType<typeof useQuery>)
    .mockReturnValueOnce({ data: userCount, isLoading: false, error: null } as ReturnType<typeof useQuery>);
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
      { material_name: "Steel", quantity: 5, threshold: 10, is_triggered: true },
      { material_name: "Copper", quantity: 2, threshold: 8, is_triggered: true },
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
    alerts: [
      { material_name: "Steel", quantity: 5, threshold: 10, is_triggered: true },
    ],
  });

  render(<Dashboard />);

  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("renders inventory level chart for admin", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.ADMIN]));
  setupQueries({
    inventoryItems: [
      { material_name: "Steel", quantity: 100, threshold: 20 },
      { material_name: "Copper", quantity: 50, threshold: 10 },
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
