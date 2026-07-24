import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { Audit } from "../Audit";
import { AuditLog } from "../types";

// ── Module mocks ──────────────────────────────────────────────────────────────

jest.mock("@tanstack/react-query", () => ({
  useQuery: jest.fn(),
}));

jest.mock("@/src/lib/api-client", () => ({
  apiClient: { get: jest.fn() },
  getResponseStatus: jest.fn(),
}));

// ── Imports after mocks ───────────────────────────────────────────────────────

import { useQuery } from "@tanstack/react-query";

const mockUseQuery = useQuery as jest.MockedFunction<typeof useQuery>;

// ── Fixtures ──────────────────────────────────────────────────────────────────

const LOGS: AuditLog[] = [
  {
    id: 12,
    user_id: 1,
    username: "admin",
    action: "create_user",
    entity_type: "user",
    entity_id: 7,
    details: { username: "testuser" },
    timestamp: "2026-07-23T23:13:07Z",
  },
  {
    id: 11,
    user_id: 999,
    username: null,
    action: "login",
    entity_type: "user",
    entity_id: 999,
    details: null,
    timestamp: "2026-07-23T23:12:59Z",
  },
];

function primeQuery(logs: AuditLog[] = LOGS) {
  mockUseQuery.mockReturnValue({
    data: { total: logs.length, page: 1, page_size: 50, results: logs },
    isLoading: false,
  } as never);
}

beforeEach(() => {
  jest.clearAllMocks();
  primeQuery();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

test("renders an audit row per entry, falling back when the actor is unknown", () => {
  render(<Audit />);

  expect(screen.getByTestId("audit-row-12")).toBeInTheDocument();
  expect(screen.getByTestId("audit-row-11")).toBeInTheDocument();

  expect(screen.getByText("admin")).toBeInTheDocument();
  expect(screen.getByText("create_user")).toBeInTheDocument();

  // A null username falls back to the id placeholder rather than rendering blank.
  expect(screen.getByText("audit.unknownUser")).toBeInTheDocument();
});

test("clicking a row expands its JSONB details, and clicking again collapses", () => {
  render(<Audit />);

  expect(screen.queryByTestId("audit-details-12")).not.toBeInTheDocument();

  fireEvent.click(screen.getByTestId("audit-row-12"));
  const details = screen.getByTestId("audit-details-12");
  expect(details).toBeInTheDocument();
  expect(details.querySelector("pre")).toHaveTextContent('"username": "testuser"');

  fireEvent.click(screen.getByTestId("audit-row-12"));
  expect(screen.queryByTestId("audit-details-12")).not.toBeInTheDocument();
});

test("filtering by action refetches with the action param and resets to page 1", () => {
  render(<Audit />);

  const before = mockUseQuery.mock.calls.length;
  fireEvent.change(screen.getByTestId("action-filter"), {
    target: { value: "login" },
  });

  const key = mockUseQuery.mock.calls.slice(before).map(
    (c) => (c[0] as { queryKey: unknown[] }).queryKey
  )[0];

  expect(key[0]).toBe("audit-logs");
  expect(key[1]).toMatchObject({ action: "login" });
  expect(key[2]).toBe(1);
});
