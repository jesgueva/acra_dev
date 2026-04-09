import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// ── Module mocks (must precede component imports) ─────────────────────────────

jest.mock("@/src/contexts/AuthContext", () => ({
  useAuth: jest.fn(),
}));

jest.mock("@tanstack/react-query", () => ({
  useQuery: jest.fn(),
  QueryClient: jest.fn(),
  QueryClientProvider: ({ children }: { children: React.ReactNode }) =>
    children,
}));

jest.mock("@/src/lib/api-client", () => ({
  apiClient: {
    get: jest.fn(),
    post: jest.fn(),
    patch: jest.fn(),
  },
}));

jest.mock("axios", () => ({
  isAxiosError: jest.fn((err) => err?.isAxiosError === true),
}));

jest.mock("@dnd-kit/core", () => ({
  DndContext: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  closestCenter: jest.fn(),
  KeyboardSensor: jest.fn(),
  PointerSensor: jest.fn(),
  useSensor: jest.fn(),
  useSensors: jest.fn(() => []),
}));

jest.mock("@dnd-kit/sortable", () => ({
  SortableContext: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
  sortableKeyboardCoordinates: jest.fn(),
  verticalListSortingStrategy: "vertical",
  useSortable: jest.fn(() => ({
    attributes: {},
    listeners: {},
    setNodeRef: jest.fn(),
    transform: null,
    transition: null,
    isDragging: false,
  })),
  arrayMove: jest.fn(<T,>(arr: T[]) => arr),
}));

jest.mock("@dnd-kit/utilities", () => ({
  CSS: { Transform: { toString: jest.fn(() => "") } },
}));

// ── Imports after mocks ───────────────────────────────────────────────────────

import { useAuth } from "@/src/contexts/AuthContext";
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "@/src/lib/api-client";
import { WorkOrders } from "../WorkOrders";
import { WorkOrderDetail } from "../WorkOrderDetail";
import { AllocateMaterialsModal } from "../AllocateMaterialsModal";
import { AssignLineDropdown } from "../AssignLineDropdown";
import { CreateWorkOrderForm } from "../CreateWorkOrderForm";
import type { WorkOrder } from "../types";
import type { AuthContextValue } from "@/src/contexts/AuthContext";
import { PRIVILEGES, ROLES } from "@/src/lib/privileges";

// ── Helpers ───────────────────────────────────────────────────────────────────

const mockUseAuth = useAuth as jest.MockedFunction<typeof useAuth>;
const mockUseQuery = useQuery as jest.MockedFunction<typeof useQuery>;
const mockApiClient = apiClient as {
  get: jest.Mock;
  post: jest.Mock;
  patch: jest.Mock;
};

function makeAuth(
  roles: string[],
  privileges: string[] = []
): AuthContextValue {
  return {
    user: {
      user_id: 1,
      full_name: "Test User",
      roles,
      preferred_language: "en",
      effective_privileges: privileges,
    },
    token: "test-token",
    isAuthenticated: true,
    login: jest.fn(),
    logout: jest.fn(),
    hasPrivilege: jest.fn((p: string) => privileges.includes(p)),
  };
}

function makeWO(overrides: Partial<WorkOrder> = {}): WorkOrder {
  return {
    id: 1,
    wo_number: "WO-001",
    product: "Widget A",
    status: "created",
    priority: "medium",
    display_sequence: 0,
    production_line: null,
    target_date: "2026-05-01",
    quantity_required: 100,
    quantity_produced: 0,
    created_by: 1,
    created_at: "2026-04-09T00:00:00Z",
    updated_at: "2026-04-09T00:00:00Z",
    materials: [],
    ...overrides,
  };
}

function setupWorkOrdersQuery(results: WorkOrder[] = []) {
  mockUseQuery.mockReturnValue({
    data: { total: results.length, page: 1, page_size: 250, results },
    isLoading: false,
    error: null,
    refetch: jest.fn(),
  } as ReturnType<typeof useQuery>);
}

beforeEach(() => {
  jest.clearAllMocks();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

test("WorkOrders: admin sees all status group sections", () => {
  mockUseAuth.mockReturnValue(
    makeAuth([ROLES.ADMIN], [PRIVILEGES.WORK_ORDERS_VIEW, PRIVILEGES.WORK_ORDERS_CREATE])
  );
  setupWorkOrdersQuery([
    makeWO({ id: 1, status: "created", product: "Widget A" }),
    makeWO({ id: 2, status: "materials_allocated", product: "Widget B" }),
    makeWO({ id: 3, status: "in_production", product: "Widget C" }),
  ]);

  render(<WorkOrders />);

  expect(screen.getByRole("region", { name: "Created" })).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "Materials Allocated" })
  ).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: "In Production" })
  ).toBeInTheDocument();
});

test("WorkOrders: Machine Operator only sees in_production group", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.OPERATOR], [PRIVILEGES.WORK_ORDERS_VIEW]));
  setupWorkOrdersQuery([
    makeWO({ id: 1, status: "created", product: "Widget A" }),
    makeWO({ id: 2, status: "in_production", product: "Widget B" }),
  ]);

  render(<WorkOrders />);

  expect(
    screen.getByRole("region", { name: "In Production" })
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Created" })
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("region", { name: "Materials Allocated" })
  ).not.toBeInTheDocument();
});

test("WorkOrderDetail: renders materials table rows", () => {
  mockUseAuth.mockReturnValue(makeAuth([ROLES.ADMIN], [PRIVILEGES.WORK_ORDERS_VIEW]));

  const wo = makeWO({
    materials: [
      { id: 1, material_type: "Steel", quantity_required: 10, quantity_allocated: 10 },
      { id: 2, material_type: "Copper", quantity_required: 5, quantity_allocated: 0 },
    ],
  });

  render(<WorkOrderDetail workOrder={wo} onClose={jest.fn()} />);

  expect(screen.getByText("Steel")).toBeInTheDocument();
  expect(screen.getByText("Copper")).toBeInTheDocument();
});

test("WorkOrderDetail: Allocate button hidden when status is not 'created'", () => {
  mockUseAuth.mockReturnValue(
    makeAuth([ROLES.ADMIN], [PRIVILEGES.WORK_ORDERS_VIEW, PRIVILEGES.WORK_ORDERS_ALLOCATE])
  );

  const wo = makeWO({ status: "materials_allocated" });
  render(<WorkOrderDetail workOrder={wo} onClose={jest.fn()} />);

  expect(
    screen.queryByRole("button", { name: /allocate materials/i })
  ).not.toBeInTheDocument();
});

test("AllocateMaterialsModal: shows insufficiency warning when open", () => {
  render(
    <AllocateMaterialsModal
      open={true}
      workOrderId={1}
      onClose={jest.fn()}
      onSuccess={jest.fn()}
    />
  );

  expect(screen.getByRole("note")).toHaveTextContent(
    /materials may be insufficient/i
  );
});

test("AllocateMaterialsModal: shows 409 inline error with material name", async () => {
  const err = Object.assign(new Error("Conflict"), {
    isAxiosError: true,
    response: {
      status: 409,
      data: { detail: "Insufficient stock for: Steel" },
    },
  });
  mockApiClient.patch.mockRejectedValueOnce(err);

  render(
    <AllocateMaterialsModal
      open={true}
      workOrderId={1}
      onClose={jest.fn()}
      onSuccess={jest.fn()}
    />
  );

  await userEvent.click(screen.getByRole("button", { name: /^allocate$/i }));

  await waitFor(() => {
    expect(screen.getByRole("alert")).toHaveTextContent("Steel");
  });
});

test("AssignLineDropdown: shows yellow capacity_warning banner", () => {
  render(
    <AssignLineDropdown
      workOrderId={1}
      currentLine={null}
      capacityWarning="Capacity exceeded for Line 1"
      onAssigned={jest.fn()}
    />
  );

  const banner = screen.getByTestId("capacity-warning");
  expect(banner).toBeInTheDocument();
  expect(banner).toHaveTextContent("Capacity exceeded for Line 1");
  expect(banner).toHaveClass("bg-yellow-50");
});

test("CreateWorkOrderForm: shows green/red material availability after submit", async () => {
  mockApiClient.post.mockResolvedValueOnce({
    data: {
      id: 1,
      wo_number: "WO-002",
      status: "created",
      material_availability: [
        { material_type: "Steel", required: 10, available: 15, sufficient: true },
        { material_type: "Copper", required: 5, available: 2, sufficient: false },
      ],
    },
  });

  render(<CreateWorkOrderForm open={true} onClose={jest.fn()} />);

  await userEvent.type(screen.getByLabelText(/product/i), "Widget X");
  await userEvent.type(screen.getByLabelText(/quantity/i), "50");
  await userEvent.type(screen.getByLabelText(/target date/i), "2026-06-01");

  const materialInputs = screen.getAllByPlaceholderText("Material type");
  const qtyInputs = screen.getAllByPlaceholderText("Qty");
  await userEvent.type(materialInputs[0], "Steel");
  await userEvent.type(qtyInputs[0], "10");

  await userEvent.click(screen.getByRole("button", { name: /^create$/i }));

  await waitFor(() => {
    expect(screen.getByText("Steel")).toBeInTheDocument();
    expect(screen.getByText("Copper")).toBeInTheDocument();
  });

  expect(screen.getByTestId("avail-Steel")).toHaveClass("text-green-600");
  expect(screen.getByTestId("avail-Copper")).toHaveClass("text-red-600");
});
