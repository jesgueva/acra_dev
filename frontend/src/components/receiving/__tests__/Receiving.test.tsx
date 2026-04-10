import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ── Module mocks ─────────────────────────────────────────────────────────────

jest.mock("@/src/lib/api-client", () => ({
  apiClient: {
    get: jest.fn(),
    post: jest.fn(),
  },
  getResponseStatus: (err: unknown) =>
    (err as { response?: { status?: number } })?.response?.status,
}));

jest.mock("sonner", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
  Toaster: () => null,
}));

// ── Imports after mocks ───────────────────────────────────────────────────────

import { apiClient } from "@/src/lib/api-client";
import { toast } from "sonner";
import OCRUploader from "../OCRUploader";
import NewDeliveryForm from "../NewDeliveryForm";
import DeliveryList from "../DeliveryList";

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeFile(name = "bol.jpg", type = "image/jpeg") {
  return new File(["data"], name, { type });
}

function makeQueryWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

const emptyPagedResponse = {
  data: { results: [], total: 0, page: 1, page_size: 20 },
};

// ── OCRUploader tests ─────────────────────────────────────────────────────────

describe("OCRUploader", () => {
  afterEach(() => jest.clearAllMocks());

  test("1: renders the drag-and-drop upload area", () => {
    render(<OCRUploader onOCRResult={jest.fn()} />);
    expect(screen.getByText("receiving.ocrDragDrop")).toBeInTheDocument();
  });

  test("2: calls onOCRResult with API data on successful upload", async () => {
    const mockResult = {
      supplier: "ACME Corp",
      carrier: "Fast Freight",
      bol_reference: "BOL-999",
      delivery_date: "2026-01-15",
      items: [
        {
          item_name: "Steel",
          description: "Steel rods",
          quantity: 10,
          pallets: 2,
          units_per_pallet: 500,
        },
      ],
      confidence: 0.95,
    };
    (apiClient.post as jest.Mock).mockResolvedValue({ data: mockResult });

    const onOCRResult = jest.fn();
    render(<OCRUploader onOCRResult={onOCRResult} />);

    const input = screen.getByLabelText("receiving.uploadFile");
    await userEvent.upload(input, makeFile());

    await waitFor(() => {
      expect(onOCRResult).toHaveBeenCalledWith(mockResult);
    });
  });

  test("3: shows error toast on 422 response", async () => {
    (apiClient.post as jest.Mock).mockRejectedValue({
      response: { status: 422 },
    });

    render(<OCRUploader onOCRResult={jest.fn()} />);

    const input = screen.getByLabelText("receiving.uploadFile");
    await userEvent.upload(input, makeFile());

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("receiving.ocrError");
    });
  });
});

// ── NewDeliveryForm tests ─────────────────────────────────────────────────────

const MOCK_PRODUCT = { id: 1, name: "Widget", category: "raw" };

describe("NewDeliveryForm", () => {
  beforeEach(() => {
    (apiClient.get as jest.Mock).mockImplementation((url: string) => {
      if (url.startsWith("/contacts")) {
        return Promise.resolve({
          data: { results: [], total: 0, page: 1, page_size: 500 },
        });
      }
      if (url.startsWith("/products")) {
        return Promise.resolve({
          data: {
            results: [MOCK_PRODUCT],
            total: 1,
            page: 1,
            page_size: 500,
          },
        });
      }
      return Promise.resolve({ data: { results: [] } });
    });
  });

  afterEach(() => jest.clearAllMocks());

  test("4: renders with exactly one item row by default", () => {
    render(<NewDeliveryForm onSuccess={jest.fn()} />, { wrapper: makeQueryWrapper() });
    expect(screen.getAllByText("receiving.product")).toHaveLength(1);
  });

  test("5: Add Item button appends a second row", async () => {
    render(<NewDeliveryForm onSuccess={jest.fn()} />, { wrapper: makeQueryWrapper() });
    await userEvent.click(screen.getByRole("button", { name: /receiving\.addItem/ }));
    expect(screen.getAllByText("receiving.product")).toHaveLength(2);
  });

  test("6: 409 response shows inline BOL error and Proceed Anyway button", async () => {
    (apiClient.post as jest.Mock).mockRejectedValue({ response: { status: 409 } });

    render(<NewDeliveryForm onSuccess={jest.fn()} />, { wrapper: makeQueryWrapper() });

    await userEvent.type(screen.getByLabelText("receiving.bolNumber"), "DUP-001");
    await userEvent.type(screen.getByLabelText("receiving.deliveryDate"), "2026-01-15");
    const productTrigger = screen
      .getByText("receiving.selectProduct")
      .closest("button");
    if (!productTrigger) throw new Error("product Select trigger not found");
    await userEvent.click(productTrigger);
    await userEvent.click(await screen.findByRole("option", { name: "Widget" }));
    await userEvent.type(screen.getByLabelText("receiving.quantity"), "5");

    await userEvent.click(screen.getByRole("button", { name: "receiving.submit" }));

    await waitFor(() => {
      expect(screen.getByText("receiving.bolDuplicate")).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: "receiving.proceedAnyway" })
      ).toBeInTheDocument();
    });
  });

  test("7: successful submission calls onSuccess", async () => {
    (apiClient.post as jest.Mock).mockResolvedValue({ data: { id: 1 } });
    const onSuccess = jest.fn();

    render(<NewDeliveryForm onSuccess={onSuccess} />, { wrapper: makeQueryWrapper() });

    await userEvent.type(screen.getByLabelText("receiving.bolNumber"), "BOL-001");
    await userEvent.type(screen.getByLabelText("receiving.deliveryDate"), "2026-01-15");
    const productTriggerOpen = screen
      .getByText("receiving.selectProduct")
      .closest("button");
    if (!productTriggerOpen) throw new Error("product Select trigger not found");
    await userEvent.click(productTriggerOpen);
    await userEvent.click(await screen.findByRole("option", { name: "Widget" }));
    await userEvent.type(screen.getByLabelText("receiving.quantity"), "5");

    await userEvent.click(screen.getByRole("button", { name: "receiving.submit" }));

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        "/deliveries",
        expect.objectContaining({
          bol_reference: "BOL-001",
          force: false,
        })
      );
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  test("8: carrier matching /transfer/i locks supplier combobox", async () => {
    render(<NewDeliveryForm onSuccess={jest.fn()} />, { wrapper: makeQueryWrapper() });

    // Open carrier combobox and type a transfer name
    const [carrierCombobox] = screen.getAllByRole("combobox");
    await userEvent.click(carrierCombobox);

    const input = await screen.findByPlaceholderText("receiving.selectCarrier");
    await userEvent.clear(input);
    await userEvent.type(input, "TRANSFERENCIA");

    // Pick the "Create TRANSFERENCIA" option
    await userEvent.click(await screen.findByText('receiving.createEntry'));

    await waitFor(() => {
      // The internalSupplier label should appear when supplier is locked
      expect(screen.getByText(/receiving\.internalSupplier/)).toBeInTheDocument();
      // The supplier combobox should be disabled
      const comboboxes = screen.getAllByRole("combobox");
      const disabledCombobox = comboboxes.find((el) => (el as HTMLButtonElement).disabled);
      expect(disabledCombobox).toBeDefined();
    });
  });
});

// ── NewDeliveryForm — OCR pre-fill ────────────────────────────────────────────

const OCR_CONTACTS = [
  { id: 1, name: "TRANSFERENCIA", type: "carrier" },
  { id: 2, name: "Internal", type: "provider" },
];

const OCR_PRODUCTS = [
  { id: 10, name: "CUBICAJE1945-3", category: "box" },
  { id: 11, name: "IRUNA18K", category: "box" },
  { id: 12, name: "CUBICAJE1879-3 COMPLETAR", category: "box" },
];

// Exact payload returned by Claude for this BOL
const CLAUDE_OCR_RESULT = {
  supplier: "Internal",
  carrier: "TRANSFERENCIA",
  bol_reference: "94808-EACRAPACK",
  delivery_date: "22/12/25",
  items: [
    {
      item_name: "CUBICAJE1945-3",
      description: "0701 234x147x152/ FM 5.2 A1 UNIT TRZ001945 REE",
      quantity: 17122,
      pallets: 11,
      units_per_pallet: 1600,
    },
    {
      item_name: "IRUNA18K",
      description: "0771B 588x390x143/ 18KG CJ AUTOMONTABLE",
      quantity: 5440,
      pallets: 10,
      units_per_pallet: 544,
    },
    {
      item_name: "CUBICAJE1879-3 COMPLETAR",
      description: "0701 502x252x305/ FM 5.2 A31 TRZ001879",
      quantity: 2880,
      pallets: 12,
      units_per_pallet: 240,
    },
  ],
  confidence: 1,
};

function makeOCRWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

describe("NewDeliveryForm — OCR pre-fill (Claude response)", () => {
  beforeEach(() => {
    (apiClient.get as jest.Mock).mockImplementation((url: string) => {
      if (url.startsWith("/contacts")) {
        return Promise.resolve({ data: { results: OCR_CONTACTS } });
      }
      if (url.startsWith("/products")) {
        return Promise.resolve({ data: { results: OCR_PRODUCTS } });
      }
      return Promise.resolve({ data: { results: [] } });
    });
  });

  afterEach(() => jest.clearAllMocks());

  test("11: pre-fills BOL reference and delivery date", async () => {
    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByDisplayValue("94808-EACRAPACK")).toBeInTheDocument();
      expect(screen.getByDisplayValue("22/12/25")).toBeInTheDocument();
    });
  });

  test("12: creates one item row per OCR item (3 rows)", async () => {
    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      // One quantity input per item row
      expect(screen.getAllByLabelText("receiving.quantity")).toHaveLength(3);
    });
  });

  test("13: populates numeric fields for each item row", async () => {
    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      const quantities = screen.getAllByLabelText("receiving.quantity") as HTMLInputElement[];
      expect(quantities[0].value).toBe("17122");
      expect(quantities[1].value).toBe("5440");
      expect(quantities[2].value).toBe("2880");

      const pallets = screen.getAllByLabelText("receiving.pallets") as HTMLInputElement[];
      expect(pallets[0].value).toBe("11");
      expect(pallets[1].value).toBe("10");
      expect(pallets[2].value).toBe("12");

      const upps = screen.getAllByLabelText("receiving.unitsPerPallet") as HTMLInputElement[];
      expect(upps[0].value).toBe("1600");
      expect(upps[1].value).toBe("544");
      expect(upps[2].value).toBe("240");
    });
  });

  test("14: populates description fields for each item row", async () => {
    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      const descs = screen.getAllByLabelText("receiving.description") as HTMLInputElement[];
      expect(descs[0].value).toBe("0701 234x147x152/ FM 5.2 A1 UNIT TRZ001945 REE");
      expect(descs[1].value).toBe("0771B 588x390x143/ 18KG CJ AUTOMONTABLE");
      expect(descs[2].value).toBe("0701 502x252x305/ FM 5.2 A31 TRZ001879");
    });
  });

  test("15: shows +478 leftover for item 0 (11×1600=17600 vs 17122)", async () => {
    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("+478.00")).toBeInTheDocument();
    });
  });

  test("16: items 1 and 2 have no leftover (exact pallet counts)", async () => {
    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      // Item 1: 10×544=5440 ✓ — Item 2: 12×240=2880 ✓
      // The "—" placeholder appears for rows without a leftover
      expect(screen.getAllByText("—")).toHaveLength(2);
    });
  });

  test("17: shows OCR carrier name in combobox button when no contact match", async () => {
    // Contacts exist but TRANSFERENCIA is not in the list → pendingLabel → shown on button
    (apiClient.get as jest.Mock).mockImplementation((url: string) => {
      if (url.startsWith("/contacts"))
        return Promise.resolve({ data: { results: [{ id: 2, name: "Internal", type: "provider" }] } });
      if (url.startsWith("/products")) return Promise.resolve({ data: { results: OCR_PRODUCTS } });
      return Promise.resolve({ data: { results: [] } });
    });

    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      // The carrier combobox button should display the pending label "TRANSFERENCIA"
      expect(screen.getByText("TRANSFERENCIA")).toBeInTheDocument();
    });
  });

  test("18: shows editable Input (not Select) for unmatched product, Select for matched", async () => {
    // IRUNA18K + CUBICAJE1879-3 COMPLETAR exist; CUBICAJE1945-3 does not
    (apiClient.get as jest.Mock).mockImplementation((url: string) => {
      if (url.startsWith("/contacts")) return Promise.resolve({ data: { results: OCR_CONTACTS } });
      if (url.startsWith("/products"))
        return Promise.resolve({ data: { results: [OCR_PRODUCTS[1], OCR_PRODUCTS[2]] } });
      return Promise.resolve({ data: { results: [] } });
    });

    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      // Unmatched product appears as an editable Input pre-filled with the OCR name
      const input = screen.getByDisplayValue("CUBICAJE1945-3") as HTMLInputElement;
      expect(input.tagName).toBe("INPUT");

      // Exactly 1 "New" badge — the 2 matched products don't get one
      expect(screen.getAllByText("receiving.newEntry")).toHaveLength(1);

      // "Pick existing" link only appears for the unmatched row
      expect(screen.getAllByText("receiving.pickExisting")).toHaveLength(1);
    });
  });

  test("19: editing the new-product Input updates the name in the row", async () => {
    (apiClient.get as jest.Mock).mockImplementation((url: string) => {
      if (url.startsWith("/contacts")) return Promise.resolve({ data: { results: OCR_CONTACTS } });
      if (url.startsWith("/products"))
        return Promise.resolve({ data: { results: [OCR_PRODUCTS[1], OCR_PRODUCTS[2]] } });
      return Promise.resolve({ data: { results: [] } });
    });

    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByDisplayValue("CUBICAJE1945-3")).toBeInTheDocument();
    });

    const input = screen.getByDisplayValue("CUBICAJE1945-3");
    await userEvent.clear(input);
    await userEvent.type(input, "CUBICAJE1945-3-FIXED");

    expect(screen.getByDisplayValue("CUBICAJE1945-3-FIXED")).toBeInTheDocument();
  });

  test("20: clicking 'Pick existing' replaces Input with the product Select", async () => {
    (apiClient.get as jest.Mock).mockImplementation((url: string) => {
      if (url.startsWith("/contacts")) return Promise.resolve({ data: { results: OCR_CONTACTS } });
      if (url.startsWith("/products"))
        return Promise.resolve({ data: { results: [OCR_PRODUCTS[1], OCR_PRODUCTS[2]] } });
      return Promise.resolve({ data: { results: [] } });
    });

    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText("receiving.pickExisting")).toBeInTheDocument();
    });

    await userEvent.click(screen.getByText("receiving.pickExisting"));

    await waitFor(() => {
      expect(screen.queryByDisplayValue("CUBICAJE1945-3")).not.toBeInTheDocument();
      expect(screen.queryByText("receiving.pickExisting")).not.toBeInTheDocument();
    });
  });

  test("17b: TRANSFERENCIA carrier locks supplier to Internal", async () => {
    render(
      <NewDeliveryForm onSuccess={jest.fn()} initialValues={CLAUDE_OCR_RESULT} />,
      { wrapper: makeOCRWrapper() },
    );

    await waitFor(() => {
      expect(screen.getByText(/receiving\.internalSupplier/)).toBeInTheDocument();
    });

    // The supplier combobox is the only disabled combobox in the form
    const comboboxes = screen.getAllByRole("combobox");
    const disabledCombobox = comboboxes.find((el) => (el as HTMLButtonElement).disabled);
    expect(disabledCombobox).toBeDefined();
    expect(disabledCombobox).toHaveTextContent("Internal");
  });
});

// ── DeliveryList tests ────────────────────────────────────────────────────────

describe("DeliveryList", () => {
  afterEach(() => jest.clearAllMocks());

  test("9: renders fetched deliveries in the table", async () => {
    (apiClient.get as jest.Mock).mockResolvedValue({
      data: {
        results: [
          {
            id: 1,
            contact_id: 1,
            contact_name: "ACME Corp",
            carrier_id: 2,
            carrier_name: "Fast Freight",
            bol_reference: "BOL-001",
            delivery_date: "2026-01-15",
            notes: null,
            created_by: 1,
            created_by_name: "Alice Clerk",
            created_at: "2026-01-15T10:00:00.000Z",
            items: [],
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
    });

    render(<DeliveryList refetch={0} />, { wrapper: makeQueryWrapper() });

    await waitFor(() => {
      expect(screen.getByText("ACME Corp")).toBeInTheDocument();
      expect(screen.getByText("BOL-001")).toBeInTheDocument();
    });
  });

  test("11: opens a detail dialog with line items when a row is clicked", async () => {
    (apiClient.get as jest.Mock).mockResolvedValue({
      data: {
        results: [
          {
            id: 1,
            contact_id: 1,
            contact_name: "ACME Corp",
            carrier_id: 2,
            carrier_name: "Fast Freight",
            bol_reference: "BOL-001",
            delivery_date: "2026-01-15",
            notes: "Gate A",
            created_by: 42,
            created_by_name: "Bob Supervisor",
            created_at: "2026-01-15T10:00:00.000Z",
            items: [
              {
                id: 10,
                product_id: 5,
                product_name: "Steel",
                description: "Rods",
                quantity: 5000,
                pallets: 2,
                units_per_pallet: 25,
                leftover: null,
                inventory_lot_id: 99,
              },
            ],
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
    });

    const user = userEvent.setup();
    render(<DeliveryList refetch={0} />, { wrapper: makeQueryWrapper() });

    await waitFor(() => expect(screen.getByText("ACME Corp")).toBeInTheDocument());

    await user.click(screen.getByText("ACME Corp"));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("BOL-001")).toBeInTheDocument();
    expect(within(dialog).getByText("Steel")).toBeInTheDocument();
    expect(within(dialog).getByText("50.00")).toBeInTheDocument();
    expect(within(dialog).getByText("Gate A")).toBeInTheDocument();
    expect(within(dialog).getByText("Bob Supervisor")).toBeInTheDocument();
  });

  test("10: re-fetches when refetch prop increments", async () => {
    (apiClient.get as jest.Mock).mockResolvedValue(emptyPagedResponse);

    const wrapper = makeQueryWrapper();
    const { rerender } = render(<DeliveryList refetch={0} />, { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));

    rerender(<DeliveryList refetch={1} />);

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });
});
