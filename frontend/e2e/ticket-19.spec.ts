import { test, expect, Page } from "@playwright/test";

/**
 * T19 — User Management & Audit UI, end to end against a live stack.
 *
 * Run against a seeded database (./scripts/reset-db-and-seed.sh) with the
 * backend on :8000 and a production frontend build on :3000.
 */

const ADMIN = { username: "admin", password: "admin123" };
const CLERK = { username: "clerk1", password: "demo123" };

// Unique per run so repeated runs against the same database do not collide.
const NEW_USER = `e2euser${Date.now().toString().slice(-6)}`;

async function login(page: Page, username: string, password: string) {
  await page.goto("/en/login");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in|iniciar|login/i }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"));
}

test.describe("T19 user management", () => {
  test("admin sees the Users and Audit nav links", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);

    await expect(page.getByRole("link", { name: "Users" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Audit Log" })).toBeVisible();
  });

  test("admin creates an operator with a production line, then deactivates them", async ({
    page,
  }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/users");

    await expect(page.getByTestId("user-table")).toBeVisible();
    await expect(page.getByTestId("user-row-1")).toBeVisible();

    // ── create ────────────────────────────────────────────────────────────────
    await page.getByTestId("new-user-button").click();
    await expect(page.getByTestId("user-form")).toBeVisible();

    await page.getByTestId("username-input").fill(NEW_USER);
    await page.getByTestId("fullname-input").fill("E2E Operator");
    await page.getByTestId("password-input").fill("temp12345");

    // The production line field is gated on the operator role.
    await expect(page.getByTestId("production-line-field")).toBeHidden();
    await page.getByTestId("role-toggle-machine_operator").click();
    await expect(page.getByTestId("production-line-field")).toBeVisible();
    await page.getByTestId("production-line-input").fill("LINE-E2E");

    await page.getByTestId("save-user").click();
    await expect(page.getByTestId("user-form")).toBeHidden();

    const row = page.locator("tr", { hasText: NEW_USER });
    await expect(row).toBeVisible();
    await expect(row).toContainText("LINE-E2E");
    await expect(row).toContainText("Machine Operator");

    // ── duplicate username → inline 409 ───────────────────────────────────────
    await page.getByTestId("new-user-button").click();
    await page.getByTestId("username-input").fill(NEW_USER);
    await page.getByTestId("fullname-input").fill("Duplicate Person");
    await page.getByTestId("password-input").fill("temp12345");
    await page.getByTestId("save-user").click();

    await expect(page.getByTestId("username-error")).toBeVisible();
    await page.getByRole("button", { name: /cancel/i }).click();

    // ── deactivate ────────────────────────────────────────────────────────────
    const rowId = await row.getAttribute("data-testid");
    const id = rowId!.replace("user-row-", "");

    await page.getByTestId(`deactivate-user-${id}`).click();
    await expect(page.getByTestId("deactivate-dialog")).toBeVisible();
    await page.getByTestId("confirm-deactivate").click();

    await expect(page.getByTestId(`user-status-${id}`)).toContainText("Inactive");
  });

  test("the last admin cannot be deactivated", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/users");

    await page.getByTestId("deactivate-user-1").click();
    await page.getByTestId("confirm-deactivate").click();

    // The backend's 409 guard surfaces as a toast and the account stays active.
    await expect(page.getByText(/last administrator/i)).toBeVisible();
    await expect(page.getByTestId("user-status-1")).toContainText("Active");
  });
});

test.describe("T19 audit log", () => {
  test("entries render with the actor and expand to show JSON details", async ({
    page,
  }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/audit");

    await expect(page.getByTestId("audit-table")).toBeVisible();

    const firstRow = page.locator("[data-testid^='audit-row-']").first();
    await expect(firstRow).toBeVisible();
    await expect(firstRow).toContainText("admin");

    const rowId = (await firstRow.getAttribute("data-testid"))!.replace(
      "audit-row-",
      ""
    );
    await firstRow.click();
    await expect(page.getByTestId(`audit-details-${rowId}`)).toBeVisible();
  });

  test("filtering by action narrows the table", async ({ page }) => {
    await login(page, ADMIN.username, ADMIN.password);
    await page.goto("/en/audit");

    await page.getByTestId("action-filter").fill("login");
    await expect(page.getByTestId("audit-table")).toBeVisible();

    const actions = page.locator("[data-testid^='audit-row-'] td:nth-child(4)");
    const count = await actions.count();
    for (let i = 0; i < count; i++) {
      await expect(actions.nth(i)).toHaveText("login");
    }
  });
});

test.describe("T19 authorization", () => {
  test("a clerk is denied both modules and sees no nav links", async ({ page }) => {
    await login(page, CLERK.username, CLERK.password);

    await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Audit Log" })).toHaveCount(0);

    // Direct URL access is refused by PrivilegeGate, not just hidden in the nav.
    await page.goto("/en/users");
    await expect(page.getByTestId("privilege-denied")).toBeVisible();

    await page.goto("/en/audit");
    await expect(page.getByTestId("privilege-denied")).toBeVisible();
  });
});
