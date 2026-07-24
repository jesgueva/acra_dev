import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { Users } from "../Users";
import { User, Role } from "../types";

// ── Module mocks ──────────────────────────────────────────────────────────────

/**
 * Radix Select renders through a portal and has no native value setter, so it is
 * swapped for a plain <select>. The trigger's `data-testid` / `id` are lifted onto
 * that element so tests target the same handle the real markup exposes.
 */
jest.mock("@/components/ui/select", () => {
  type ElementWithProps = React.ReactElement<Record<string, unknown>>;
  return {
    Select: ({
      value,
      onValueChange,
      children,
    }: {
      value: string;
      onValueChange: (v: string) => void;
      children: React.ReactNode;
    }) => {
      const kids = React.Children.toArray(children) as ElementWithProps[];
      const trigger = kids.find((c) => c.props?.["data-testid"] !== undefined);
      return (
        <select
          data-testid={trigger?.props["data-testid"] as string}
          id={trigger?.props.id as string}
          value={value}
          onChange={(e) => onValueChange(e.target.value)}
        >
          {kids.filter((c) => c.props?.["data-testid"] === undefined)}
        </select>
      );
    },
    SelectTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    SelectValue: () => null,
    SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => (
      <option value={value}>{children}</option>
    ),
  };
});

jest.mock("@tanstack/react-query", () => ({
  useQuery: jest.fn(),
  useQueryClient: jest.fn(() => ({ invalidateQueries: jest.fn() })),
}));

jest.mock("@/src/lib/api-client", () => ({
  apiClient: { get: jest.fn(), post: jest.fn(), patch: jest.fn() },
  getResponseStatus: jest.fn(),
}));

jest.mock("sonner", () => ({
  toast: { success: jest.fn(), error: jest.fn() },
}));

// ── Imports after mocks ───────────────────────────────────────────────────────

import { useQuery } from "@tanstack/react-query";
import { apiClient, getResponseStatus } from "@/src/lib/api-client";

const mockUseQuery = useQuery as jest.MockedFunction<typeof useQuery>;
const mockPost = apiClient.post as jest.Mock;
const mockStatus = getResponseStatus as jest.Mock;

// ── Fixtures ──────────────────────────────────────────────────────────────────

const ROLE_LIST: Role[] = [
  { id: 1, role_name: "company_admin", description: "Full system access" },
  { id: 2, role_name: "receiving_clerk", description: null },
  { id: 3, role_name: "production_supervisor", description: null },
  { id: 4, role_name: "machine_operator", description: null },
];

const USER_LIST: User[] = [
  {
    id: 1,
    username: "admin",
    full_name: "Administrator",
    roles: ["company_admin"],
    preferred_language: "en",
    production_line: null,
    status: "active",
    created_at: "2026-06-24T03:39:29Z",
  },
  {
    id: 5,
    username: "operator1",
    full_name: "Diego Ramos",
    roles: ["machine_operator"],
    preferred_language: "es",
    production_line: "LINE-A",
    status: "inactive",
    created_at: "2026-06-24T03:39:29Z",
  },
];

/** Route each useQuery call by its queryKey, mirroring Users.tsx. */
function primeQueries(users: User[] = USER_LIST, loading = false) {
  mockUseQuery.mockImplementation((opts: unknown) => {
    const key = (opts as { queryKey: unknown[] }).queryKey[0];
    if (key === "roles") {
      return { data: { results: ROLE_LIST }, isLoading: false } as never;
    }
    return {
      data: { total: users.length, page: 1, page_size: 20, results: users },
      isLoading: loading,
    } as never;
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  primeQueries();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

test("renders a row per user with role, production line, and status", () => {
  render(<Users />);

  expect(screen.getByTestId("user-row-1")).toBeInTheDocument();
  expect(screen.getByTestId("user-row-5")).toBeInTheDocument();

  // Scoped to the table — the role filter renders the same labels as options.
  const table = within(screen.getByTestId("user-table"));
  // Slugs are humanized for display, never shown raw.
  expect(table.getByText("Company Admin")).toBeInTheDocument();
  expect(table.getByText("Machine Operator")).toBeInTheDocument();
  expect(table.queryByText("company_admin")).not.toBeInTheDocument();

  expect(table.getByText("LINE-A")).toBeInTheDocument();
  expect(screen.getByTestId("user-status-1")).toHaveTextContent("users.statusActive");
  expect(screen.getByTestId("user-status-5")).toHaveTextContent("users.statusInactive");
});

test("changing the status filter refetches with the new filter", () => {
  render(<Users />);

  const before = mockUseQuery.mock.calls.length;
  fireEvent.change(screen.getByTestId("status-filter"), {
    target: { value: "inactive" },
  });

  const userQuery = mockUseQuery.mock.calls
    .slice(before)
    .map((c) => (c[0] as { queryKey: unknown[] }).queryKey)
    .find((k) => k[0] === "users");

  expect(userQuery).toBeDefined();
  expect(userQuery![1]).toMatchObject({ status: "inactive" });
});

test("the production line field appears only once the operator role is selected", () => {
  render(<Users />);
  fireEvent.click(screen.getByTestId("new-user-button"));

  // Hidden for a non-operator role...
  expect(screen.queryByTestId("production-line-field")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("role-toggle-receiving_clerk"));
  expect(screen.queryByTestId("production-line-field")).not.toBeInTheDocument();

  // ...and revealed by the operator role.
  fireEvent.click(screen.getByTestId("role-toggle-machine_operator"));
  expect(screen.getByTestId("production-line-field")).toBeInTheDocument();

  // Deselecting hides it again.
  fireEvent.click(screen.getByTestId("role-toggle-machine_operator"));
  expect(screen.queryByTestId("production-line-field")).not.toBeInTheDocument();
});

test("a 409 on create shows an inline error under the username field", async () => {
  mockPost.mockRejectedValue(new Error("conflict"));
  mockStatus.mockReturnValue(409);

  render(<Users />);
  fireEvent.click(screen.getByTestId("new-user-button"));

  fireEvent.change(screen.getByTestId("username-input"), {
    target: { value: "admin" },
  });
  fireEvent.change(screen.getByTestId("fullname-input"), {
    target: { value: "Duplicate Person" },
  });
  fireEvent.change(screen.getByTestId("password-input"), {
    target: { value: "temp123" },
  });
  fireEvent.click(screen.getByTestId("save-user"));

  await waitFor(() => {
    expect(screen.getByTestId("username-error")).toHaveTextContent(
      "users.usernameExists"
    );
  });

  // The inline field error is used instead of the generic form-level alert.
  expect(screen.queryByTestId("user-form-error")).not.toBeInTheDocument();
});
