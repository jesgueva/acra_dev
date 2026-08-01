import path from "path";
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
 * T21 Flow 7 — OCR-assisted receiving (FR-002, FR-003; UC-001 steps 3–6 and E1).
 *
 * Flow 2 covers UC-001's manual path (alternate flow A1). This one covers the path the SRS leads
 * with: scan the bill of lading, let the extraction fill the form, correct it, then confirm.
 *
 * **The OCR endpoint is stubbed at the network boundary**, not called for real. `POST
 * /deliveries/ocr` hands the image to Gemini/Anthropic, so an unstubbed test would need live API
 * keys, cost money per run, take seconds against NFR-002's 10s budget, and fail whenever the model
 * phrased itself differently. What is under test here is the contract the UI depends on — given a
 * well-formed `OCRResponse`, does the form populate, can the clerk correct it, and is the
 * *corrected* value what reaches inventory — which is exactly the part that regresses when the
 * receiving form changes. The extraction quality itself belongs to the backend's own tests.
 */

/** Mirrors `OCRResponse` in `backend/app/schemas/delivery.py`. */
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
}

/**
 * Intercept the OCR call and answer with `body`.
 *
 * Matched on the path alone so the stub survives the suite being pointed at another host with
 * E2E_API_URL.
 */
async function stubOCR(page: Page, body: OCRStub) {
  await page.route("**/api/v1/deliveries/ocr", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    }),
  );
}

/** Intercept the OCR call and fail it the way the backend does on an unreadable document. */
async function stubOCRFailure(page: Page) {
  await page.route("**/api/v1/deliveries/ocr", (route) =>
    route.fulfill({
      status: 422,
      contentType: "application/json",
      // The shape the router raises when `ocr_service` comes back with confidence 0.0.
      body: JSON.stringify({ detail: "Unable to extract data from the document." }),
    }),
  );
}

/**
 * Put a file on the hidden input.
 *
 * The bytes are irrelevant — the response is stubbed — but the upload has to be a real
 * `setInputFiles` so the component's own `FormData`/`processFile` path runs rather than being
 * bypassed by calling the callback directly.
 */
async function uploadBOL(page: Page) {
  await page.locator("#ocr-file-input").setInputFiles({
    name: "bol.png",
    mimeType: "image/png",
    buffer: Buffer.from("not-a-real-image-the-endpoint-is-stubbed"),
  });
}

/** A seeded provider, carrier and product, so the form's name-matching has something to match. */
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

test.describe("T21 Flow 7 — OCR-assisted receiving", () => {
  test.beforeEach(({ page }) => failOnPageErrors(page));

  test("an uploaded BOL populates the delivery form (UC-001 steps 3–5)", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, USERS.admin);
    const { provider, carrier, product } = await seedNames(request, token);
    const bol = unique("OCR-BOL-");

    await login(page, USERS.clerk);
    await stubOCR(page, {
      supplier: provider.name,
      carrier: carrier.name,
      bol_reference: bol,
      delivery_date: "23/07/26",
      items: [{ item_name: product.name, quantity: 7 }],
      confidence: 0.95,
    });

    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();

    // The form starts empty — otherwise "it populated" proves nothing.
    await expect(page.getByTestId("bol-input")).toHaveValue("");

    await uploadBOL(page);

    await expect(page.getByText("Document processed successfully.")).toBeVisible();

    // Step 5: every extracted field lands in the form.
    await expect(page.getByTestId("bol-input")).toHaveValue(bol);
    await expect(page.getByTestId("delivery-date-input")).toHaveValue("23/07/26");
    await expect(page.getByTestId("quantity-0")).toHaveValue("7");
    // Names are resolved to the seeded records rather than left as loose text.
    await expect(page.getByTestId("supplier-combobox")).toContainText(provider.name);
    await expect(page.getByTestId("carrier-combobox")).toContainText(carrier.name);
    await expect(page.getByTestId("product-select-0")).toContainText(product.name);
  });

  test("a correction to the extracted data is what reaches inventory (FR-003)", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, USERS.admin);
    const { provider, carrier, product } = await seedNames(request, token);
    const before = inStorageTotal(await allLots(request, token), product.id);

    const bol = unique("OCR-FIX-");
    const OCR_QUANTITY = 99; // what the "scan" claims …
    const CORRECTED = 4; //     … and what the clerk says it really was

    await login(page, USERS.clerk);
    await stubOCR(page, {
      supplier: provider.name,
      carrier: carrier.name,
      bol_reference: bol,
      delivery_date: "23/07/26",
      items: [{ item_name: product.name, quantity: OCR_QUANTITY }],
      confidence: 0.62,
    });

    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();
    await uploadBOL(page);
    await expect(page.getByTestId("quantity-0")).toHaveValue(String(OCR_QUANTITY));

    // Step 6: the clerk overrides a misread quantity before confirming.
    await page.getByTestId("quantity-0").fill(String(CORRECTED));
    await page.getByTestId("submit-delivery").click();

    await expect(page.locator("tr", { hasText: bol })).toBeVisible();

    // The assertion that matters: OCR is a suggestion, not the source of truth. Stock moved by the
    // corrected amount, and the 99 the model hallucinated never touched the ledger.
    const after = inStorageTotal(await allLots(request, token), product.id);
    expect(after).toBe(before + CORRECTED * 100);
  });

  test("a material the catalogue does not know is offered as a new product", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, USERS.admin);
    const { provider, carrier } = await seedNames(request, token);
    const unknownMaterial = unique("Reclaimed Nylon ");

    await login(page, USERS.clerk);
    await stubOCR(page, {
      supplier: provider.name,
      carrier: carrier.name,
      bol_reference: unique("OCR-NEW-"),
      delivery_date: "23/07/26",
      items: [{ item_name: unknownMaterial, quantity: 3 }],
      confidence: 0.8,
    });

    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();
    await uploadBOL(page);

    // An unmatched name must not be silently dropped — it comes back as an editable new-product
    // field carrying the extracted text, so the clerk can accept or rename it.
    const newProduct = page.locator("#new_product_0");
    await expect(newProduct).toBeVisible();
    await expect(newProduct).toHaveValue(unknownMaterial);
    await expect(page.getByTestId("quantity-0")).toHaveValue("3");
  });

  test("E1 — an unreadable document asks for manual entry and clears nothing", async ({
    page,
  }) => {
    await login(page, USERS.clerk);
    await stubOCRFailure(page);

    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();

    // Something the clerk typed before reaching for the scanner, to prove a failed extraction is
    // not allowed to wipe the form out from under them.
    const typed = unique("MANUAL-");
    await page.getByTestId("bol-input").fill(typed);

    await uploadBOL(page);

    await expect(page.getByText("Unable to extract data. Please enter manually.")).toBeVisible();

    // The fallback to alternate flow A1 has to still be possible: the form is intact and usable.
    await expect(page.getByTestId("bol-input")).toHaveValue(typed);
    await expect(page.getByTestId("delivery-form")).toBeVisible();
  });

  test("ACR-50 — mock mode extracts for real, with no API key and no client-side stub", async ({
    page,
  }) => {
    // Requires the backend under test to be running with OCR_MOCK_MODE=true (see
    // docker-compose.yml / .github/workflows/ci.yml) — everything else in this file stubs
    // `/deliveries/ocr` at the network boundary, but this test deliberately does not, to prove the
    // real endpoint is runnable with zero external API calls.
    test.skip(
      process.env.OCR_MOCK_MODE !== "true",
      "backend must be running with OCR_MOCK_MODE=true — export it before this run",
    );

    await login(page, USERS.clerk);
    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();

    const fixture = path.join(
      __dirname,
      "../../backend/tests/fixtures/ocr/sample_bol_gridded.png",
    );
    await page.locator("#ocr-file-input").setInputFiles(fixture);

    await expect(page.getByText("Document processed successfully.")).toBeVisible();

    // The canned response `ocr_service._mock_response()` returns — supplier/carrier/product are
    // not seeded, so they land as editable "new entry" fields rather than matched comboboxes.
    await expect(page.getByTestId("bol-input")).toHaveValue("BOL-2026-0623");
    await expect(page.getByTestId("delivery-date-input")).toHaveValue("2026-06-23");
    await expect(page.getByTestId("supplier-combobox")).toContainText("Acme Steel Supply Co.");
    await expect(page.getByTestId("carrier-combobox")).toContainText("Iberia Logistics S.L.");
    await expect(page.locator("#new_product_0")).toHaveValue("Galvanized Steel Sheet");
    await expect(page.getByTestId("quantity-0")).toHaveValue("1000");
  });

  test("the OCR endpoint refuses a user without deliveries.create", async ({ request }) => {
    // A hidden button is not a permission — PRV-003 has to hold at the API too.
    const operatorToken = await apiToken(request, USERS.operator);

    const res = await request.post(`${API}/api/v1/deliveries/ocr`, {
      headers: authHeaders(operatorToken),
      multipart: {
        file: {
          name: "bol.png",
          mimeType: "image/png",
          buffer: Buffer.from("irrelevant"),
        },
      },
    });

    expect(res.status()).toBe(403);
  });
});
