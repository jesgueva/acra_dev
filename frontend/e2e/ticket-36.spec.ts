import { test, expect, type Page } from "@playwright/test";
import {
  USERS,
  API,
  login,
  apiToken,
  authHeaders,
  unique,
  failOnPageErrors,
} from "./helpers/auth";
import { allLots, inStorageTotal } from "./helpers/inventory";

/**
 * ACR-36 / A8-4 — the receiving UI against the enriched OCR response.
 *
 * The backend response grew two fields: `provider` (which model answered) and `header_fill_rate`
 * (the honestly-named twin of `confidence`). The extraction *quality* is measured by the backend
 * bench against a labelled corpus — `backend/scripts/ocr_bench/` — and not here; what these tests
 * protect is the UI contract around the new shape:
 *
 *  1. The added fields do not disturb form population.
 *  2. The Claude fallback populates identically to the Gemini primary — a clerk must not be able
 *     to tell which model answered.
 *  3. `confidence` is still never rendered. It counts non-empty header fields, so four *wrong*
 *     values score 1.0; showing it as a quality signal would actively mislead the clerk into
 *     trusting a bad extraction. This test is what stops someone "helpfully" surfacing it later.
 *  4. Corrections still win over the extraction.
 *
 * The endpoint stays stubbed at the network boundary, for the reasons `ticket-21-ocr.spec.ts`
 * documents: real calls need keys, cost money, and vary run to run.
 */

/** Mirrors `OCRResponse` in `backend/app/schemas/delivery.py` as of ACR-36. */
interface OCRStub {
  supplier?: string;
  carrier?: string;
  bol_reference?: string;
  delivery_date?: string;
  items?: Array<{
    item_name: string;
    description?: string;
    quantity: number;
    pallets?: number;
    units_per_pallet?: number;
  }>;
  confidence: number;
  header_fill_rate?: number;
  provider?: string;
}

async function stubOCR(page: Page, body: OCRStub) {
  await page.route("**/api/v1/deliveries/ocr", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    }),
  );
}

async function uploadBOL(page: Page) {
  await page.locator("#ocr-file-input").setInputFiles({
    name: "bol.png",
    mimeType: "image/png",
    buffer: Buffer.from("not-a-real-image-the-endpoint-is-stubbed"),
  });
}

async function seedNames(request: Parameters<typeof apiToken>[0], token: string) {
  const contactsRes = await request.get(`${API}/api/v1/contacts?page_size=100`, {
    headers: authHeaders(token),
  });
  const contacts = (await contactsRes.json()).results as {
    id: number;
    name: string;
    type: string;
  }[];

  const productsRes = await request.get(`${API}/api/v1/products?page_size=5`, {
    headers: authHeaders(token),
  });
  const product = (await productsRes.json()).results[0] as { id: number; name: string };

  return {
    provider: contacts.find((c) => c.type === "provider")!,
    carrier: contacts.find((c) => c.type === "carrier")!,
    product,
  };
}

test.describe("ACR-36 — enriched OCR response in the receiving flow", () => {
  test.beforeEach(({ page }) => failOnPageErrors(page));

  test("the added provider / fill-rate fields do not disturb form population", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, USERS.admin);
    const { provider, carrier, product } = await seedNames(request, token);
    const bol = unique("A84-GEM-");

    await login(page, USERS.clerk);
    await stubOCR(page, {
      supplier: provider.name,
      carrier: carrier.name,
      bol_reference: bol,
      delivery_date: "23/07/26",
      items: [{ item_name: product.name, quantity: 7, pallets: 2, units_per_pallet: 4 }],
      confidence: 1.0,
      header_fill_rate: 1.0,
      provider: "gemini",
    });

    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();
    await expect(page.getByTestId("bol-input")).toHaveValue("");

    await uploadBOL(page);

    await expect(page.getByTestId("bol-input")).toHaveValue(bol);
    await expect(page.getByTestId("delivery-date-input")).toHaveValue("23/07/26");
    await expect(page.getByTestId("quantity-0")).toHaveValue("7");
    await expect(page.getByTestId("supplier-combobox")).toContainText(provider.name);
    await expect(page.getByTestId("carrier-combobox")).toContainText(carrier.name);
    await expect(page.getByTestId("product-select-0")).toContainText(product.name);
  });

  test("the Claude fallback populates the form identically to the Gemini primary", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, USERS.admin);
    const { provider, carrier, product } = await seedNames(request, token);
    const bol = unique("A84-CLD-");

    await login(page, USERS.clerk);
    await stubOCR(page, {
      supplier: provider.name,
      carrier: carrier.name,
      bol_reference: bol,
      delivery_date: "23/07/26",
      items: [{ item_name: product.name, quantity: 7, pallets: 2, units_per_pallet: 4 }],
      confidence: 1.0,
      header_fill_rate: 1.0,
      // The primary failed and the fallback carried the request. The clerk should not be able to
      // tell, and nothing in the form should branch on it.
      provider: "claude",
    });

    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();
    await uploadBOL(page);

    await expect(page.getByTestId("bol-input")).toHaveValue(bol);
    await expect(page.getByTestId("quantity-0")).toHaveValue("7");
    await expect(page.getByTestId("product-select-0")).toContainText(product.name);
  });

  test("a confident-looking but wrong extraction is not presented as trustworthy", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, USERS.admin);
    const { provider, carrier, product } = await seedNames(request, token);
    const bol = unique("A84-FILL-");

    await login(page, USERS.clerk);
    // Every header field is populated, so `confidence` is 1.0 — and every value could still be
    // wrong. The UI must not translate that into a quality claim anywhere on the page.
    await stubOCR(page, {
      supplier: provider.name,
      carrier: carrier.name,
      bol_reference: bol,
      delivery_date: "23/07/26",
      items: [{ item_name: product.name, quantity: 7 }],
      confidence: 1.0,
      header_fill_rate: 1.0,
      provider: "gemini",
    });

    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();
    await uploadBOL(page);
    await expect(page.getByTestId("bol-input")).toHaveValue(bol);

    const form = page.getByTestId("delivery-form");
    await expect(form).not.toContainText(/confidence/i);
    await expect(form).not.toContainText(/accuracy/i);
    await expect(form).not.toContainText(/100%/);
  });

  test("a correction still overrides the extraction end to end", async ({ page, request }) => {
    const token = await apiToken(request, USERS.admin);
    const { provider, carrier, product } = await seedNames(request, token);
    const before = inStorageTotal(await allLots(request, token), product.id);

    const bol = unique("A84-FIX-");
    const EXTRACTED = 88;
    const CORRECTED = 3;

    await login(page, USERS.clerk);
    await stubOCR(page, {
      supplier: provider.name,
      carrier: carrier.name,
      bol_reference: bol,
      delivery_date: "23/07/26",
      items: [{ item_name: product.name, quantity: EXTRACTED }],
      confidence: 1.0,
      header_fill_rate: 1.0,
      provider: "claude",
    });

    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();
    await uploadBOL(page);
    await expect(page.getByTestId("quantity-0")).toHaveValue(String(EXTRACTED));

    await page.getByTestId("quantity-0").fill(String(CORRECTED));
    await page.getByTestId("submit-delivery").click();

    await expect(page.locator("tr", { hasText: bol })).toBeVisible();

    // A fill rate of 1.0 buys the extraction no authority: the clerk's number is what moves stock.
    const after = inStorageTotal(await allLots(request, token), product.id);
    expect(after).toBe(before + CORRECTED * 100);
  });
});
