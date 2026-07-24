import React from "react";
import { render, screen } from "@testing-library/react";
import { PRIVILEGES } from "@/src/lib/privileges";
import type { AuthContextValue } from "@/src/contexts/AuthContext";

// ── Module mocks ──────────────────────────────────────────────────────────────

jest.mock("@tanstack/react-query", () => ({
  useQuery: jest.fn(),
  useMutation: jest.fn(() => ({ mutate: jest.fn(), isPending: false })),
  useQueryClient: jest.fn(() => ({ invalidateQueries: jest.fn() })),
}));

jest.mock("@/src/lib/api-client", () => ({
  apiClient: { get: jest.fn(), post: jest.fn() },
}));

jest.mock("@/src/contexts/AuthContext", () => ({
  useAuth: jest.fn(),
}));

// ── Imports after mocks ───────────────────────────────────────────────────────

import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/src/contexts/AuthContext";
import { ShippingView } from "../ShippingView";

const mockUseQuery = useQuery as jest.MockedFunction<typeof useQuery>;
const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;

// ── Fixtures ──────────────────────────────────────────────────────────────────

const SHIPMENT = {
  id: 1,
  contact_id: 10,
  contact_name: "Acme Corp",
  carrier_id: 20,
  carrier_name: "Fast Freight",
  bol_number: "AV26-0001",
  shipment_date: "2026-04-09",
  notes: null,
  type: "customer_order",
  created_by: 1,
  created_at: "2026-04-09T00:00:00Z",
  items: [
    { id: 100, lot_id: 1, quantity: 5000, product_name: "Steel Rod", lot_number: "LOT-0001" },
  ],
};

function makeAuth(privileges: string[]): AuthContextValue {
  return {
    user: {
      user_id: 1,
      full_name: "Test User",
      roles: ["production_supervisor"],
      preferred_language: "en",
      effective_privileges: privileges,
    },
    token: "tok",
    isAuthenticated: true,
    authResolved: true,
    login: jest.fn(),
    logout: jest.fn(),
    hasPrivilege: (p: string) => privileges.includes(p),
  };
}

/** ShippingView issues three useQuery calls; only the shipments one drives the table. */
function mockQueries({
  data,
  isLoading = false,
  isError = false,
}: {
  data?: unknown;
  isLoading?: boolean;
  isError?: boolean;
}) {
  mockUseQuery.mockImplementation((options: { queryKey: unknown[] }) => {
    if (options.queryKey[0] === "shipments") {
      return { data, isLoading, isError } as ReturnType<typeof useQuery>;
    }
    return { data: { results: [], total: 0 } } as ReturnType<typeof useQuery>;
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockUseAuth.mockReturnValue(makeAuth([PRIVILEGES.SHIPPING_VIEW, PRIVILEGES.SHIPPING_CREATE]));
});

// ── Tests ─────────────────────────────────────────────────────────────────────

test("renders the shipment log from the list response", () => {
  mockQueries({ data: { total: 1, page: 1, page_size: 20, results: [SHIPMENT] } });

  render(<ShippingView />);

  expect(screen.getByText("AV26-0001")).toBeInTheDocument();
  expect(screen.getByText("Acme Corp")).toBeInTheDocument();
  expect(screen.getByText("Fast Freight")).toBeInTheDocument();
  expect(screen.getByText("shipping.customerOrder")).toBeInTheDocument();
});

test("renders the empty state rather than crashing on zero shipments", () => {
  mockQueries({ data: { total: 0, page: 1, page_size: 20, results: [] } });

  render(<ShippingView />);

  expect(screen.getByText("shipping.noShipments")).toBeInTheDocument();
});

test("renders an error alert when the list request fails", () => {
  mockQueries({ isError: true });

  render(<ShippingView />);

  expect(screen.getByText("common.error")).toBeInTheDocument();
  expect(screen.queryByText("shipping.noShipments")).not.toBeInTheDocument();
});

test("shows the New Shipment button to a user holding shipping.create", () => {
  mockQueries({ data: { total: 0, page: 1, page_size: 20, results: [] } });

  render(<ShippingView />);

  expect(screen.getByText("shipping.newShipment")).toBeInTheDocument();
});

test("hides the New Shipment button from a view-only user", () => {
  // ACR-35 grants shipping.view to the supervisor but withholds shipping.create, so the button
  // would submit into a 403. It must not render at all.
  mockUseAuth.mockReturnValue(makeAuth([PRIVILEGES.SHIPPING_VIEW]));
  mockQueries({ data: { total: 0, page: 1, page_size: 20, results: [SHIPMENT] } });

  render(<ShippingView />);

  expect(screen.queryByText("shipping.newShipment")).not.toBeInTheDocument();
  // The log itself stays readable — view-only means view, not blocked.
  expect(screen.getByText("AV26-0001")).toBeInTheDocument();
});
