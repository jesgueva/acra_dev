import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { ShippingView } from "../ShippingView";

// ── Module mocks ──────────────────────────────────────────────────────────────

// Radix's Select never opens in jsdom; a native <select> keeps the value wiring testable.
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
      data-testid="select"
      value={value}
      onChange={(e) => onValueChange(e.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: ({ children, id }: { children: React.ReactNode; id?: string }) => (
    <span data-select-trigger={id}>{children}</span>
  ),
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}));

jest.mock("@tanstack/react-query", () => ({
  useQuery: jest.fn(),
  useMutation: jest.fn(),
  useQueryClient: jest.fn(() => ({
    invalidateQueries: jest.fn(),
    setQueryData: jest.fn(),
  })),
}));

jest.mock("@/src/lib/api-client", () => ({
  apiClient: { get: jest.fn(), post: jest.fn() },
}));

const mockUseQuery = useQuery as jest.Mock;
const mockUseMutation = useMutation as jest.Mock;

// ── Fixtures ──────────────────────────────────────────────────────────────────

const DIRECT_SHIPMENT = {
  id: 1,
  contact_id: 10,
  contact_name: "Acme Corp",
  carrier_id: 20,
  carrier_name: "Fast Freight",
  bol_number: "AV26-0001",
  shipment_date: "2026-07-23",
  notes: null,
  type: "direct_customer",
  source: "SC",
  created_by: 1,
  created_at: "2026-07-23T00:00:00Z",
  items: [
    {
      id: 100,
      lot_id: 1,
      quantity: 5000,
      unit_price: 250,
      product_name: "Steel Rod",
      lot_number: "LOT-0001",
    },
  ],
};

const TRANSFER_SHIPMENT = {
  ...DIRECT_SHIPMENT,
  id: 2,
  bol_number: "AV26-0002",
  type: "transfer",
  source: null,
};

const INVOICE = {
  id: 1,
  shipment_id: 1,
  invoice_number: "INV-2026-00001",
  invoice_date: "2026-07-23",
  currency: "USD",
  subtotal_amount: 12500,
  tax_amount: 0,
  total_amount: 12500,
  status: "issued",
  lines: [
    {
      id: 1,
      shipment_item_id: 100,
      description: "Steel Rod (lot LOT-0001)",
      quantity: 5000,
      unit_price: 250,
      line_total: 12500,
    },
  ],
};

function listResult(results: unknown[]) {
  return { total: results.length, page: 1, page_size: 20, results };
}

/**
 * The component fires four queries; route each by its key so a test can set one
 * without having to describe the other three.
 */
function setupQueries({
  shipments = listResult([]),
  shipmentsState = {},
  invoice = null,
  invoiceLoading = false,
}: {
  shipments?: unknown;
  shipmentsState?: Record<string, unknown>;
  invoice?: unknown;
  invoiceLoading?: boolean;
} = {}) {
  mockUseQuery.mockImplementation(({ queryKey }: { queryKey: unknown[] }) => {
    if (queryKey[0] === "shipments") {
      return { data: shipments, isLoading: false, isError: false, ...shipmentsState };
    }
    if (queryKey[0] === "invoice") {
      return { data: invoice, isLoading: invoiceLoading, isError: false };
    }
    return { data: { results: [], total: 0 }, isLoading: false, isError: false };
  });
}

const mutate = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  mockUseMutation.mockReturnValue({ mutate, isPending: false });
  setupQueries();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("ShippingView — list states", () => {
  it("renders skeletons while loading", () => {
    setupQueries({ shipmentsState: { isLoading: true, data: undefined } });
    const { container } = render(<ShippingView />);
    expect(container.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);
  });

  it("renders an alert when the list fails", () => {
    setupQueries({ shipmentsState: { isError: true, data: undefined } });
    render(<ShippingView />);
    expect(screen.getByRole("alert")).toHaveTextContent("common.error");
  });

  it("renders the empty state when there are no shipments", () => {
    render(<ShippingView />);
    expect(screen.getByText("shipping.noShipments")).toBeInTheDocument();
  });

  it("renders a row per shipment", () => {
    setupQueries({ shipments: listResult([DIRECT_SHIPMENT, TRANSFER_SHIPMENT]) });
    render(<ShippingView />);
    expect(screen.getByText("AV26-0001")).toBeInTheDocument();
    expect(screen.getByText("AV26-0002")).toBeInTheDocument();
  });
});

describe("ShippingView — Transfer / Direct Customer (§4.3)", () => {
  it("labels each shipment with its domain-model type", () => {
    setupQueries({ shipments: listResult([DIRECT_SHIPMENT, TRANSFER_SHIPMENT]) });
    render(<ShippingView />);
    expect(screen.getAllByText("shipping.directCustomer").length).toBeGreaterThan(0);
    expect(screen.getAllByText("shipping.transfer").length).toBeGreaterThan(0);
  });

  it("shows the source of a Direct Customer shipment in the list", () => {
    setupQueries({ shipments: listResult([DIRECT_SHIPMENT]) });
    render(<ShippingView />);
    expect(screen.getByText("SC")).toBeInTheDocument();
  });

  it("offers the source field for a Direct Customer shipment", () => {
    render(<ShippingView />);
    fireEvent.click(screen.getByText("shipping.newShipment"));
    // direct_customer is the default type, so source is available immediately.
    expect(screen.getByLabelText("shipping.source")).toBeInTheDocument();
  });

  it("hides the source field once the type switches to Transfer", () => {
    render(<ShippingView />);
    fireEvent.click(screen.getByText("shipping.newShipment"));

    const typeSelect = screen
      .getAllByTestId("select")
      .find((el) => within(el).queryByText("shipping.transfer"));
    expect(typeSelect).toBeDefined();

    fireEvent.change(typeSelect!, { target: { value: "transfer" } });

    expect(screen.queryByLabelText("shipping.source")).not.toBeInTheDocument();
  });
});

describe("ShippingView — create form validation", () => {
  /** The browser blocks submit on empty `required` fields, so fill them to reach our own checks. */
  function fillRequiredHeader() {
    fireEvent.change(screen.getByLabelText("shipping.bolNumber *"), {
      target: { value: "AV26-0009" },
    });
    fireEvent.change(screen.getByLabelText("shipping.shipmentDate *"), {
      target: { value: "2026-07-23" },
    });
  }

  it("blocks submit when no line has both a lot and a quantity", () => {
    render(<ShippingView />);
    fireEvent.click(screen.getByText("shipping.newShipment"));
    fillRequiredHeader();
    fireEvent.click(screen.getByText("shipping.submit"));

    expect(screen.getByRole("alert")).toHaveTextContent("shipping.noValidLines");
    expect(mutate).not.toHaveBeenCalled();
  });

  it("submits a priced line with the source attached", () => {
    render(<ShippingView />);
    fireEvent.click(screen.getByText("shipping.newShipment"));

    fireEvent.change(screen.getByLabelText("shipping.bolNumber *"), {
      target: { value: "AV26-0009" },
    });
    fireEvent.change(screen.getByLabelText("shipping.shipmentDate *"), {
      target: { value: "2026-07-23" },
    });
    fireEvent.change(screen.getByLabelText("shipping.source"), {
      target: { value: "SC" },
    });
    fireEvent.change(screen.getByLabelText("shipping.lotId 1"), {
      target: { value: "1" },
    });
    fireEvent.change(screen.getByLabelText("shipping.quantity 1"), {
      target: { value: "50" },
    });
    fireEvent.change(screen.getByLabelText("shipping.unitPrice 1"), {
      target: { value: "2.50" },
    });

    fireEvent.click(screen.getByText("shipping.submit"));

    expect(mutate).toHaveBeenCalledTimes(1);
    const body = mutate.mock.calls[0][0];
    expect(body.type).toBe("direct_customer");
    expect(body.source).toBe("SC");
    // Quantities and prices go over the wire as integers ×100.
    expect(body.items).toEqual([{ lot_id: 1, quantity: 5000, unit_price: 250 }]);
  });

  it("omits unit_price when the operator leaves it blank", () => {
    render(<ShippingView />);
    fireEvent.click(screen.getByText("shipping.newShipment"));
    fillRequiredHeader();

    fireEvent.change(screen.getByLabelText("shipping.lotId 1"), {
      target: { value: "3" },
    });
    fireEvent.change(screen.getByLabelText("shipping.quantity 1"), {
      target: { value: "10" },
    });
    fireEvent.click(screen.getByText("shipping.submit"));

    expect(mutate.mock.calls[0][0].items).toEqual([{ lot_id: 3, quantity: 1000 }]);
  });

  it("does not send a source that was typed before switching to Transfer", () => {
    render(<ShippingView />);
    fireEvent.click(screen.getByText("shipping.newShipment"));
    fillRequiredHeader();

    fireEvent.change(screen.getByLabelText("shipping.source"), {
      target: { value: "SC" },
    });
    const typeSelect = screen
      .getAllByTestId("select")
      .find((el) => within(el).queryByText("shipping.transfer"));
    fireEvent.change(typeSelect!, { target: { value: "transfer" } });

    fireEvent.change(screen.getByLabelText("shipping.lotId 1"), {
      target: { value: "1" },
    });
    fireEvent.change(screen.getByLabelText("shipping.quantity 1"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByText("shipping.submit"));

    const body = mutate.mock.calls[0][0];
    expect(body.type).toBe("transfer");
    expect(body.source).toBeUndefined();
  });
});

describe("ShippingView — invoice panel", () => {
  function openDetail() {
    fireEvent.click(screen.getByText("AV26-0001"));
  }

  it("offers to generate an invoice when the shipment has none", () => {
    setupQueries({ shipments: listResult([DIRECT_SHIPMENT]), invoice: null });
    render(<ShippingView />);
    openDetail();

    expect(screen.getByText("shipping.noInvoice")).toBeInTheDocument();
    expect(screen.getByText("shipping.generateInvoice")).toBeInTheDocument();
  });

  it("generates the invoice for the open shipment", () => {
    setupQueries({ shipments: listResult([DIRECT_SHIPMENT]), invoice: null });
    render(<ShippingView />);
    openDetail();
    fireEvent.click(screen.getByText("shipping.generateInvoice"));

    expect(mutate).toHaveBeenCalledWith(1);
  });

  it("renders the invoice number and totals once one exists", () => {
    setupQueries({ shipments: listResult([DIRECT_SHIPMENT]), invoice: INVOICE });
    render(<ShippingView />);
    openDetail();

    expect(screen.getByText("INV-2026-00001")).toBeInTheDocument();
    expect(screen.getByText("Steel Rod (lot LOT-0001)")).toBeInTheDocument();
    // 12500 (×100) renders as 125.00
    expect(screen.getAllByText("125.00").length).toBeGreaterThan(0);
    expect(screen.getByText("125.00 USD")).toBeInTheDocument();
  });

  it("hides the generate button once an invoice exists", () => {
    setupQueries({ shipments: listResult([DIRECT_SHIPMENT]), invoice: INVOICE });
    render(<ShippingView />);
    openDetail();

    expect(screen.queryByText("shipping.generateInvoice")).not.toBeInTheDocument();
  });
});
