import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { DeliveryNotesView } from "../DeliveryNotesView";

// ── Module mocks ──────────────────────────────────────────────────────────────

jest.mock("@tanstack/react-query", () => ({
  useQuery: jest.fn(),
}));

jest.mock("@/src/lib/api-client", () => ({
  apiClient: { get: jest.fn() },
}));

// ── Imports after mocks ───────────────────────────────────────────────────────

import { useQuery } from "@tanstack/react-query";

const mockUseQuery = useQuery as jest.MockedFunction<typeof useQuery>;

// ── Fixtures ──────────────────────────────────────────────────────────────────

const NOTES = [
  {
    id: 1,
    type: "inbound",
    source: null,
    partner_id: 10,
    partner_name: "Acme Provider",
    document_number: "BOL-2026-001",
    document_date: "2026-07-01",
    uploaded: true,
    notes: null,
    created_by: 1,
    created_at: "2026-07-01T10:00:00Z",
  },
  {
    id: 2,
    type: "direct_customer",
    source: "SC",
    partner_id: 20,
    partner_name: "Beta Client",
    document_number: "AV26-0002",
    document_date: "2026-07-04",
    uploaded: false,
    notes: null,
    created_by: 1,
    created_at: "2026-07-04T10:00:00Z",
  },
  {
    id: 3,
    type: "internal",
    source: null,
    partner_id: null,
    partner_name: null,
    document_number: "INT-20260723-0001",
    document_date: "2026-07-23",
    uploaded: false,
    notes: "worksheet 42 approved",
    created_by: 2,
    created_at: "2026-07-23T10:00:00Z",
  },
];

function primeQuery(overrides: Record<string, unknown> = {}) {
  mockUseQuery.mockReturnValue({
    data: { total: NOTES.length, page: 1, page_size: 20, results: NOTES },
    isLoading: false,
    isError: false,
    ...overrides,
  } as never);
}

beforeEach(() => {
  jest.clearAllMocks();
  primeQuery();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("DeliveryNotesView", () => {
  it("renders a row per delivery note", () => {
    render(<DeliveryNotesView />);
    expect(screen.getByText("BOL-2026-001")).toBeInTheDocument();
    expect(screen.getByText("AV26-0002")).toBeInTheDocument();
    expect(screen.getByText("INT-20260723-0001")).toBeInTheDocument();
  });

  it("shows the partner, falling back to a dash for internal notes", () => {
    render(<DeliveryNotesView />);
    expect(screen.getByText("Acme Provider")).toBeInTheDocument();
    expect(screen.getByText("Beta Client")).toBeInTheDocument();
    // An internal note has no counterparty and no source — two dashes on that row.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });

  it("renders the §4.3 source only where one exists", () => {
    render(<DeliveryNotesView />);
    expect(screen.getByText("SC")).toBeInTheDocument();
  });

  it("distinguishes uploaded from system-generated provenance", () => {
    render(<DeliveryNotesView />);
    expect(screen.getByText("deliveryNotes.uploaded")).toBeInTheDocument();
    expect(screen.getAllByText("deliveryNotes.systemGenerated")).toHaveLength(2);
  });

  it("renders a skeleton while loading", () => {
    primeQuery({ data: undefined, isLoading: true });
    render(<DeliveryNotesView />);
    expect(screen.getByTestId("delivery-notes-loading")).toBeInTheDocument();
    expect(screen.queryByText("BOL-2026-001")).not.toBeInTheDocument();
  });

  it("renders an error alert when the query fails", () => {
    primeQuery({ data: undefined, isLoading: false, isError: true });
    render(<DeliveryNotesView />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("BOL-2026-001")).not.toBeInTheDocument();
  });

  it("renders an empty state when there are no notes", () => {
    primeQuery({ data: { total: 0, page: 1, page_size: 20, results: [] } });
    render(<DeliveryNotesView />);
    expect(screen.getByText("deliveryNotes.noNotes")).toBeInTheDocument();
  });

  it("refetches with the date filter applied", () => {
    render(<DeliveryNotesView />);
    const before = mockUseQuery.mock.calls.length;

    fireEvent.change(screen.getByLabelText("deliveryNotes.dateFrom"), {
      target: { value: "2026-07-02" },
    });

    expect(mockUseQuery.mock.calls.length).toBeGreaterThan(before);
    const lastCall = mockUseQuery.mock.calls[mockUseQuery.mock.calls.length - 1][0];
    expect((lastCall as { queryKey: unknown[] }).queryKey).toContain("2026-07-02");
  });

  it("offers a clear-filters control only once a filter is set", () => {
    render(<DeliveryNotesView />);
    expect(screen.queryByText("deliveryNotes.clearFilters")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("deliveryNotes.dateTo"), {
      target: { value: "2026-07-31" },
    });

    expect(screen.getByText("deliveryNotes.clearFilters")).toBeInTheDocument();
  });

  it("hides pagination when everything fits on one page", () => {
    render(<DeliveryNotesView />);
    expect(screen.queryByText("common.previous")).not.toBeInTheDocument();
  });

  it("shows pagination once the result set spans pages", () => {
    primeQuery({ data: { total: 45, page: 1, page_size: 20, results: NOTES } });
    render(<DeliveryNotesView />);
    expect(screen.getByText("common.previous")).toBeInTheDocument();
    expect(screen.getByText("common.next")).toBeInTheDocument();
  });
});
