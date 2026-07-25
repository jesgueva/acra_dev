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
 * T21 Flow 2 — Receiving a delivery.
 *
 * Clerk logs in, records a delivery, and the goods show up in inventory. The last part is the
 * point: a delivery that does not move stock has not really been received.
 */

const QUANTITY = 12; // display units; the ledger stores ×100

/**
 * Open a CreatableCombobox and return its search box.
 *
 * The popover's search field cannot be found by placeholder — `Combobox` passes the *same*
 * `placeholder` to both the trigger and the `CommandInput` — and `role="combobox"` matches the
 * trigger too. `[cmdk-input]` is the one unambiguous handle.
 */
async function openCombobox(page: Page, testId: string) {
  await page.getByTestId(testId).getByRole("combobox").click();
  // `.last()` because a previously opened popover can still be mounted while it animates out, so
  // more than one `[cmdk-input]` may exist; the one just opened is the most recently portalled.
  const input = page.locator("[cmdk-input]").last();
  await expect(input).toBeVisible();
  return input;
}

/** Pick an existing option out of a CreatableCombobox. */
async function chooseFromCombobox(page: Page, testId: string, label: string) {
  const input = await openCombobox(page, testId);
  await input.fill(label);
  await page.getByRole("option", { name: label, exact: true }).click();
}

/** Fill the whole delivery form. Returns the BOL reference used. */
async function fillDelivery(
  page: Page,
  { carrier, provider, product, quantity = String(QUANTITY) }: {
    carrier: string;
    provider: string;
    product: string;
    quantity?: string;
  },
) {
  const bol = unique("E2E-BOL-");

  await chooseFromCombobox(page, "carrier-combobox", carrier);
  await chooseFromCombobox(page, "supplier-combobox", provider);

  await page.getByTestId("bol-input").fill(bol);
  await page.getByTestId("delivery-date-input").fill("23/07/26");

  await page.getByTestId("product-select-0").click();
  await page.getByRole("option", { name: product, exact: true }).click();
  await page.getByTestId("quantity-0").fill(quantity);

  return bol;
}

test.describe("T21 Flow 2 — receiving a delivery", () => {
  test.beforeEach(({ page }) => failOnPageErrors(page));

  test("a clerk records a delivery and the goods land in inventory", async ({
    page,
    request,
  }) => {
    const adminToken = await apiToken(request, USERS.admin);

    // Read the product's on-hand *before*, so the assertion holds on a database that earlier runs
    // have already moved.
    const productsRes = await request.get(`${API}/api/v1/products?page_size=5`, {
      headers: authHeaders(adminToken),
    });
    const product = (await productsRes.json()).results[0];
    const before = inStorageTotal(await allLots(request, adminToken), product.id);

    const contactsRes = await request.get(`${API}/api/v1/contacts?page_size=50`, {
      headers: authHeaders(adminToken),
    });
    const contacts = (await contactsRes.json()).results as {
      id: number;
      name: string;
      type: string;
    }[];
    const carrier = contacts.find((c) => c.type === "carrier")!;
    const provider = contacts.find((c) => c.type === "provider")!;

    await login(page, USERS.clerk);
    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();

    const bol = await fillDelivery(page, {
      carrier: carrier.name,
      provider: provider.name,
      product: product.name,
    });
    await page.getByTestId("submit-delivery").click();

    // It shows up in the history list…
    const row = page.locator("tr", { hasText: bol });
    await expect(row).toBeVisible();
    await expect(row).toContainText(carrier.name);

    // …and opening it shows what was recorded.
    await row.click();
    const detail = page.getByTestId("delivery-detail");
    await expect(detail).toBeVisible();
    await expect(detail).toContainText(bol);

    // The whole point of receiving: stock went up by exactly what was entered.
    const after = inStorageTotal(await allLots(request, adminToken), product.id);
    expect(after).toBe(before + QUANTITY * 100);
  });

  test("an incomplete form is refused and creates nothing", async ({ page, request }) => {
    const token = await apiToken(request, USERS.clerk);
    const countBefore = async () => {
      const res = await request.get(`${API}/api/v1/deliveries?page_size=1`, {
        headers: authHeaders(token),
      });
      return (await res.json()).total as number;
    };
    const before = await countBefore();

    await login(page, USERS.clerk);
    await page.goto("/en/receiving");
    await expect(page.getByTestId("delivery-form")).toBeVisible();

    // Everything empty — the required attributes must stop this at the browser.
    await page.getByTestId("submit-delivery").click();
    await expect(page.getByTestId("delivery-form")).toBeVisible();

    // BOL present but no product selected — the form's own guard, not the browser's.
    await page.getByTestId("bol-input").fill(unique("E2E-NOPROD-"));
    await page.getByTestId("delivery-date-input").fill("23/07/26");
    await page.getByTestId("quantity-0").fill("5");
    await page.getByTestId("submit-delivery").click();
    await expect(page.getByTestId("delivery-error")).toBeVisible();

    expect(await countBefore()).toBe(before);
  });

  test("a whitespace-only BOL reference is refused", async ({ page, request }) => {
    const contactsRes = await request.get(`${API}/api/v1/contacts?page_size=50`, {
      headers: authHeaders(await apiToken(request, USERS.admin)),
    });
    const contacts = (await contactsRes.json()).results as {
      id: number;
      name: string;
      type: string;
    }[];

    await login(page, USERS.clerk);
    await page.goto("/en/receiving");

    await chooseFromCombobox(
      page,
      "carrier-combobox",
      contacts.find((c) => c.type === "carrier")!.name,
    );
    await page.getByTestId("bol-input").fill("   ");
    await page.getByTestId("delivery-date-input").fill("23/07/26");
    await page.getByTestId("quantity-0").fill("5");
    await page.getByTestId("submit-delivery").click();

    // Either the form blocks it or the API does, but a blank BOL must never become a delivery.
    await expect(page.getByTestId("delivery-form")).toBeVisible();
    const res = await request.get(`${API}/api/v1/deliveries?page_size=100`, {
      headers: authHeaders(await apiToken(request, USERS.clerk)),
    });
    const blank = ((await res.json()).results as { bol_reference: string }[]).filter(
      (d) => !d.bol_reference.trim(),
    );
    expect(blank, "a blank BOL reference must not reach the database").toHaveLength(0);
  });

  test("re-using a BOL reference warns before it duplicates", async ({ page, request }) => {
    const adminToken = await apiToken(request, USERS.admin);
    const contactsRes = await request.get(`${API}/api/v1/contacts?page_size=50`, {
      headers: authHeaders(adminToken),
    });
    const contacts = (await contactsRes.json()).results as {
      id: number;
      name: string;
      type: string;
    }[];
    const carrier = contacts.find((c) => c.type === "carrier")!;
    const provider = contacts.find((c) => c.type === "provider")!;
    const productsRes = await request.get(`${API}/api/v1/products?page_size=5`, {
      headers: authHeaders(adminToken),
    });
    const product = (await productsRes.json()).results[0];

    await login(page, USERS.clerk);
    await page.goto("/en/receiving");

    const bol = await fillDelivery(page, {
      carrier: carrier.name,
      provider: provider.name,
      product: product.name,
    });
    await page.getByTestId("submit-delivery").click();
    await expect(page.locator("tr", { hasText: bol })).toBeVisible();

    // Same BOL again → the duplicate warning, with an explicit override rather than a silent second
    // delivery.
    await chooseFromCombobox(page, "carrier-combobox", carrier.name);
    await chooseFromCombobox(page, "supplier-combobox", provider.name);
    await page.getByTestId("bol-input").fill(bol);
    await page.getByTestId("delivery-date-input").fill("23/07/26");
    await page.getByTestId("product-select-0").click();
    await page.getByRole("option", { name: product.name, exact: true }).click();
    await page.getByTestId("quantity-0").fill("3");
    await page.getByTestId("submit-delivery").click();

    await expect(page.getByTestId("bol-duplicate")).toBeVisible();
  });

  test("an admin can create a carrier inline while recording a delivery", async ({
    page,
    request,
  }) => {
    const adminToken = await apiToken(request, USERS.admin);
    const productsRes = await request.get(`${API}/api/v1/products?page_size=5`, {
      headers: authHeaders(adminToken),
    });
    const product = (await productsRes.json()).results[0];
    const contactsRes = await request.get(`${API}/api/v1/contacts?page_size=50`, {
      headers: authHeaders(adminToken),
    });
    const provider = ((await contactsRes.json()).results as { name: string; type: string }[]).find(
      (c) => c.type === "provider",
    )!;

    const newCarrier = unique("E2E Carrier ");

    await login(page, USERS.admin);
    await page.goto("/en/receiving");

    // The inline-create path: type a name that does not exist, take the "create" option.
    const carrierInput = await openCombobox(page, "carrier-combobox");
    await carrierInput.fill(newCarrier);
    await page.getByRole("option", { name: new RegExp(newCarrier) }).click();

    await chooseFromCombobox(page, "supplier-combobox", provider.name);
    const bol = unique("E2E-INLINE-");
    await page.getByTestId("bol-input").fill(bol);
    await page.getByTestId("delivery-date-input").fill("23/07/26");
    await page.getByTestId("product-select-0").click();
    await page.getByRole("option", { name: product.name, exact: true }).click();
    await page.getByTestId("quantity-0").fill("4");
    await page.getByTestId("submit-delivery").click();

    const row = page.locator("tr", { hasText: bol });
    await expect(row).toBeVisible();
    await expect(row).toContainText(newCarrier);

    // The contact was really created, not just rendered optimistically.
    const after = await request.get(`${API}/api/v1/contacts?page_size=200`, {
      headers: authHeaders(adminToken),
    });
    const names = ((await after.json()).results as { name: string }[]).map((c) => c.name);
    expect(names).toContain(newCarrier);
  });

  test("a machine operator is blocked from receiving at the page and at the API", async ({
    page,
    request,
  }) => {
    await login(page, USERS.operator);

    await expect(page.getByRole("link", { name: "Receiving" })).toHaveCount(0);

    await page.goto("/en/receiving");
    await expect(page.getByTestId("privilege-denied")).toBeVisible();
    await expect(page.getByTestId("delivery-form")).toHaveCount(0);

    const token = await apiToken(request, USERS.operator);
    const create = await request.post(`${API}/api/v1/deliveries`, {
      headers: authHeaders(token),
      data: {
        bol_reference: unique("E2E-FORBIDDEN-"),
        delivery_date: "23/07/26",
        items: [{ product_id: 1, quantity: 100 }],
      },
    });
    expect(create.status()).toBe(403);
  });
});
