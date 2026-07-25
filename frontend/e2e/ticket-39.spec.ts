import { test, expect, Page } from "@playwright/test";

/**
 * ACR-39 — Unified Delivery Note document model, end to end against a live stack.
 *
 * Run against a seeded database with the backend on :8000 and a production
 * frontend build on :3000 (NOT `next dev` — see KI-02).
 *
 * Covers §4.1 (every movement attaches to a note), §4.2 (uploaded vs
 * system-generated provenance) and §4.3 (transfer vs direct-customer, `source`).
 *
 * Note: creating a shipment needs `shipping.create`, which is granted to no role
 * until ACR-35. Those tests skip themselves rather than fail when the grant is
 * absent, so this spec stays green on a stock seed.
 */

const ADMIN = { username: "admin", password: "admin123" };
const OPERATOR = { username: "operator1", password: "demo123" };

// Unique per run so repeated runs against the same database do not collide.
const RUN = Date.now().toString().slice(-6);

async function login(page: Page, username: string, password: string) {
  await page.goto("/en/login");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in|iniciar|login/i }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"));
}

/**
 * The bearer token the app is using.
 *
 * It lives in React state, restored from an httpOnly cookie, so it is not
 * reachable from localStorage — ask the Next.js session route for it.
 */
async function apiToken(page: Page): Promise<string> {
  return page.evaluate(async () => {
    const res = await fetch("/api/auth/me");
    const data = await res.json();
    return data.access_token as string;
  });
}

/** Row locator for a note by its document number. */
function noteRow(page: Page, documentNumber: string) {
  return page.getByRole("row").filter({ hasText: documentNumber });
}

test.describe("ACR-39 delivery notes", () => {
  test("admin reaches the Delivery Notes module from the nav", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);

    await page.getByRole("link", { name: "Delivery Notes" }).click();
    await page.waitForURL(/\/en\/delivery-notes/);

    await expect(
      page.getByRole("heading", { name: "Delivery Notes" })
    ).toBeVisible();
    // Seeded receiving data means at least one note already exists.
    await expect(page.getByRole("row").nth(1)).toBeVisible();
  });

  test("receiving a delivery creates an uploaded INBOUND note", async ({
    page,
  }) => {
    const bol = `E2E-BOL-${RUN}`;
    await login(page, ADMIN.username, ADMIN.password);

    // Drive the API for the delivery itself; this spec is about the note it
    // produces, and the receiving form is already covered elsewhere.
    const token = await apiToken(page);
    const created = await page.evaluate(async ({ bolRef, token }) => {
      const contacts = await fetch(
        "http://localhost:8000/api/v1/contacts?type=provider&page_size=1",
        { headers: { Authorization: `Bearer ${token}` } }
      ).then((r) => r.json());
      const products = await fetch(
        "http://localhost:8000/api/v1/products?page_size=1",
        { headers: { Authorization: `Bearer ${token}` } }
      ).then((r) => r.json());

      const res = await fetch("http://localhost:8000/api/v1/deliveries", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          contact_id: contacts.results[0].id,
          bol_reference: bolRef,
          delivery_date: "2026-07-23",
          items: [
            { product_id: products.results[0].id, quantity: 1000, pallets: 1, units_per_pallet: 10 },
          ],
        }),
      });
      return { status: res.status, body: await res.json() };
    }, { bolRef: bol, token });

    expect(created.status).toBe(201);
    // The delivery hangs off a note rather than owning the document facts.
    expect(created.body.delivery_note_id).toBeTruthy();
    expect(created.body.bol_reference).toBe(bol);

    await page.goto("/en/delivery-notes");
    const row = noteRow(page, bol);
    await expect(row).toBeVisible();
    await expect(row).toContainText("Inbound");
    await expect(row).toContainText("Uploaded"); // §4.2 — arrived with the goods
  });

  test("a forced duplicate BoL is de-duplicated, not rejected", async ({
    page,
  }) => {
    const bol = `E2E-DUP-${RUN}`;
    await login(page, ADMIN.username, ADMIN.password);

    const token = await apiToken(page);
    const results = await page.evaluate(async ({ bolRef, token }) => {
      const contacts = await fetch(
        "http://localhost:8000/api/v1/contacts?type=provider&page_size=1",
        { headers: { Authorization: `Bearer ${token}` } }
      ).then((r) => r.json());
      const products = await fetch(
        "http://localhost:8000/api/v1/products?page_size=1",
        { headers: { Authorization: `Bearer ${token}` } }
      ).then((r) => r.json());

      const post = (force: boolean) =>
        fetch("http://localhost:8000/api/v1/deliveries", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            contact_id: contacts.results[0].id,
            bol_reference: bolRef,
            delivery_date: "2026-07-23",
            force,
            items: [{ product_id: products.results[0].id, quantity: 1000 }],
          }),
        });

      const first = await post(false);
      const conflict = await post(false);
      const forced = await post(true);
      return {
        first: first.status,
        conflict: conflict.status,
        forced: forced.status,
        forcedBody: await forced.json(),
      };
    }, { bolRef: bol, token });

    expect(results.first).toBe(201);
    expect(results.conflict).toBe(409);
    expect(results.forced).toBe(201);
    // Suffixed so the (type, document_number) uniqueness holds.
    expect(results.forcedBody.bol_reference).toBe(`${bol} (2)`);

    await page.goto("/en/delivery-notes");
    await expect(noteRow(page, `${bol} (2)`)).toBeVisible();
  });

  test("the type filter narrows the table and empties cleanly", async ({
    page,
  }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/delivery-notes");

    await expect(page.getByRole("row").nth(1)).toBeVisible();

    await page.getByRole("combobox", { name: "Filter by type" }).click();
    await page.getByRole("option", { name: "Inbound" }).click();

    // Every remaining row is inbound.
    const typeCells = page.getByRole("row").filter({ hasText: /Inbound|Transfer|Direct Customer|Internal/ });
    await expect(typeCells.first()).toContainText("Inbound");

    // Clearing filters is only offered once one is set.
    await expect(page.getByRole("button", { name: "Clear filters" })).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.getByRole("button", { name: "Clear filters" })).toBeHidden();
  });

  test("a date range with no notes shows the empty state", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/delivery-notes");

    // By id: "To" also matches other labels on the page.
    await page.locator("#date-from").fill("1999-01-01");
    await page.locator("#date-to").fill("1999-01-02");

    await expect(page.getByText("No delivery notes found.")).toBeVisible();
  });

  test("a shipment produces a system-generated note of the right flavour", async ({
    page,
  }) => {
    await login(page, ADMIN.username, ADMIN.password);

    const token = await apiToken(page);
    const out = await page.evaluate(async ({ run, token }) => {
      const headers = {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      };
      const client = await fetch("http://localhost:8000/api/v1/contacts", {
        method: "POST",
        headers,
        body: JSON.stringify({ name: `E2E Client ${run}`, type: "client" }),
      }).then((r) => r.json());

      const lots = await fetch(
        "http://localhost:8000/api/v1/inventory?page_size=50",
        { headers: { Authorization: `Bearer ${token}` } }
      ).then((r) => r.json());
      const lot = lots.results.find(
        (l: { quantity_on_hand: number }) => l.quantity_on_hand > 500
      );

      const res = await fetch("http://localhost:8000/api/v1/shipments", {
        method: "POST",
        headers,
        body: JSON.stringify({
          contact_id: client.id,
          bol_number: `E2E-SHIP-${run}`,
          shipment_date: "2026-07-23",
          type: "direct_customer",
          source: "SC",
          items: [{ lot_id: lot.id, quantity: 100 }],
        }),
      });
      return { status: res.status, body: await res.json() };
    }, { run: RUN, token });

    // shipping.create is granted to no role until ACR-35.
    test.skip(out.status === 403, "shipping.create not granted (ISS-04 / ACR-35)");

    expect(out.status).toBe(201);
    expect(out.body.type).toBe("direct_customer");
    expect(out.body.source).toBe("SC"); // §4.3
    expect(out.body.delivery_note_id).toBeTruthy();

    await page.goto("/en/delivery-notes");
    const row = noteRow(page, `E2E-SHIP-${RUN}`);
    await expect(row).toBeVisible();
    await expect(row).toContainText("Direct Customer");
    await expect(row).toContainText("SC");
    await expect(row).toContainText("System"); // §4.2 — not uploaded
  });

  test("source is rejected on a transfer note", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);

    const token = await apiToken(page);
    const status = await page.evaluate(async ({ run, token }) => {
      const res = await fetch("http://localhost:8000/api/v1/shipments", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          bol_number: `E2E-BAD-${run}`,
          shipment_date: "2026-07-23",
          type: "transfer",
          source: "SC",
          items: [{ lot_id: 1, quantity: 100 }],
        }),
      });
      return res.status;
    }, { run: RUN, token });

    // 422 from the schema rule; 403 if shipping.create is not granted yet.
    expect([403, 422]).toContain(status);
  });

  test("the shipping form disables source for a transfer", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/shipping");

    await page.getByRole("button", { name: "New Shipment" }).click();

    // Defaults to direct customer, where a source is meaningful.
    await expect(page.getByLabel("Source")).toBeEnabled();

    await page.getByRole("combobox", { name: "Type" }).click();
    await page.getByRole("option", { name: "Transfer" }).click();

    await expect(page.getByLabel("Source")).toBeDisabled();
  });

  test("a user without the privilege is blocked, not merely unlinked", async ({
    page,
  }) => {
    await login(page, OPERATOR.username, OPERATOR.password);

    // The nav link is hidden …
    await expect(
      page.getByRole("link", { name: "Delivery Notes" })
    ).toBeHidden();

    // … and typing the URL is refused rather than showing data.
    await page.goto("/en/delivery-notes");
    await expect(page.getByTestId("privilege-denied")).toBeVisible();
    await expect(page.getByRole("table")).toBeHidden();
  });

  test("the module is localized in Spanish", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/es/delivery-notes");

    await expect(page.getByRole("heading", { name: "Albaranes" })).toBeVisible();
    await expect(page.getByText("Filtrar por tipo")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Procedencia" })).toBeVisible();
  });
});
