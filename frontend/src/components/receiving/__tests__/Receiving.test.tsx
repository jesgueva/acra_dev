import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
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

describe("NewDeliveryForm", () => {
  afterEach(() => jest.clearAllMocks());

  test("4: renders with exactly one item row by default", () => {
    render(<NewDeliveryForm onSuccess={jest.fn()} />);
    expect(screen.getAllByText("receiving.itemName")).toHaveLength(1);
  });

  test("5: Add Item button appends a second row", async () => {
    render(<NewDeliveryForm onSuccess={jest.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: /receiving\.addItem/ }));
    expect(screen.getAllByText("receiving.itemName")).toHaveLength(2);
  });

  test("6: 409 response shows inline BOL error and Proceed Anyway button", async () => {
    (apiClient.post as jest.Mock).mockRejectedValue({ response: { status: 409 } });

    render(<NewDeliveryForm onSuccess={jest.fn()} />);

    await userEvent.type(screen.getByLabelText("receiving.carrier"), "Fast Freight");
    await userEvent.type(screen.getByLabelText("receiving.supplier"), "ACME");
    await userEvent.type(screen.getByLabelText("receiving.bolNumber"), "DUP-001");
    await userEvent.type(screen.getByLabelText("receiving.deliveryDate"), "2026-01-15");
    await userEvent.type(screen.getByLabelText("receiving.itemName"), "Steel");
    await userEvent.type(screen.getByLabelText("receiving.quantity"), "5");

    await userEvent.click(screen.getByRole("button", { name: "receiving.submit" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("receiving.bolDuplicate");
      expect(
        screen.getByRole("button", { name: "receiving.proceedAnyway" })
      ).toBeInTheDocument();
    });
  });

  test("7: successful submission calls onSuccess", async () => {
    (apiClient.post as jest.Mock).mockResolvedValue({ data: { id: 1 } });
    const onSuccess = jest.fn();

    render(<NewDeliveryForm onSuccess={onSuccess} />);

    await userEvent.type(screen.getByLabelText("receiving.carrier"), "Fast Freight");
    await userEvent.type(screen.getByLabelText("receiving.supplier"), "ACME");
    await userEvent.type(screen.getByLabelText("receiving.bolNumber"), "BOL-001");
    await userEvent.type(screen.getByLabelText("receiving.deliveryDate"), "2026-01-15");
    await userEvent.type(screen.getByLabelText("receiving.itemName"), "Steel");
    await userEvent.type(screen.getByLabelText("receiving.quantity"), "5");

    await userEvent.click(screen.getByRole("button", { name: "receiving.submit" }));

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        "/deliveries",
        expect.objectContaining({
          supplier: "ACME",
          carrier: "Fast Freight",
          bol_reference: "BOL-001",
          force: false,
        })
      );
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  test("8: carrier matching /transfer/i locks supplier to Internal", async () => {
    render(<NewDeliveryForm onSuccess={jest.fn()} />);

    const carrierInput = screen.getByLabelText("receiving.carrier");
    await userEvent.type(carrierInput, "TRANSFERENCIA");

    await waitFor(() => {
      const supplierInput = screen.getByLabelText("receiving.supplier") as HTMLInputElement;
      expect(supplierInput.value).toBe("Internal");
      expect(supplierInput.readOnly).toBe(true);
    });
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
            supplier: "ACME Corp",
            carrier: "Fast Freight",
            bol_reference: "BOL-001",
            delivery_date: "2026-01-15",
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

  test("10: re-fetches when refetch prop increments", async () => {
    (apiClient.get as jest.Mock).mockResolvedValue(emptyPagedResponse);

    const wrapper = makeQueryWrapper();
    const { rerender } = render(<DeliveryList refetch={0} />, { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));

    rerender(<DeliveryList refetch={1} />);

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  });
});
