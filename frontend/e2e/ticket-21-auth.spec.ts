import { test, expect } from "@playwright/test";
import { USERS, login, failOnPageErrors } from "./helpers/auth";

/**
 * T21 Flow 1 — Authentication.
 *
 * Wrong creds → error; correct creds → the app; cookie persists; logout. Plus the ticket's explicit
 * accessibility requirement: the whole flow must be completable with Tab + Enter alone.
 *
 * Run against a seeded database with the backend up and a production frontend build serving
 * `E2E_BASE_URL` (`npm run build && npm run start` — never `next dev`, see KI-02).
 */

test.describe("T21 Flow 1 — authentication", () => {
  test.beforeEach(({ page }) => failOnPageErrors(page));

  test("a wrong password is refused and leaves the user on the login page", async ({ page }) => {
    await page.goto("/en/login");

    await page.locator("#username").fill(USERS.admin.username);
    await page.locator("#password").fill("definitely-not-the-password");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page.getByTestId("login-error")).toContainText(/invalid username or password/i);
    await expect(page).toHaveURL(/\/en\/login/);

    // The failure must not leave a usable session behind.
    await page.goto("/en/inventory");
    await expect(page).toHaveURL(/\/en\/login/);
  });

  test("an unknown username is refused the same way, with no 500", async ({ page }) => {
    await page.goto("/en/login");

    await page.locator("#username").fill("no-such-person");
    await page.locator("#password").fill("whatever123");
    await page.getByRole("button", { name: /sign in/i }).click();

    // Deliberately the same message as a wrong password — telling the two apart would let an
    // attacker enumerate valid usernames.
    await expect(page.getByTestId("login-error")).toContainText(/invalid username or password/i);
    await expect(page).toHaveURL(/\/en\/login/);
  });

  test("an empty submit is blocked by the form and never reaches the API", async ({ page }) => {
    await page.goto("/en/login");

    let loginCalls = 0;
    page.on("request", (req) => {
      if (req.url().includes("/auth/login")) loginCalls += 1;
    });

    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page).toHaveURL(/\/en\/login/);
    expect(loginCalls, "an empty form must not hit the login endpoint").toBe(0);
  });

  test("whitespace-only credentials are refused", async ({ page }) => {
    await page.goto("/en/login");

    await page.locator("#username").fill("   ");
    await page.locator("#password").fill("   ");
    await page.getByRole("button", { name: /sign in/i }).click();

    await expect(page).toHaveURL(/\/en\/login/);
    await expect(page.getByTestId("login-error")).toBeVisible();
  });

  test("correct credentials sign the user in and the session survives a reload", async ({
    page,
  }) => {
    await login(page, USERS.admin);

    // AuthForm sends an authenticated user to the dashboard — the one module every role can see.
    await expect(page).toHaveURL(/\/en\/dashboard/);
    await expect(page.getByRole("complementary", { name: "sidebar" })).toBeVisible();

    await page.reload();
    await expect(page).toHaveURL(/\/en\/dashboard/);
    await expect(page.getByRole("complementary", { name: "sidebar" })).toBeVisible();

    // A fresh navigation, not just a reload — proves the cookie, not in-memory React state.
    await page.goto("/en/inventory");
    await expect(page.getByTestId("inventory-table")).toBeVisible();
  });

  test("every role lands somewhere it is allowed to be", async ({ page }) => {
    // Login used to send everyone to /receiving, which production_supervisor and machine_operator
    // have no privilege for — so a correct login dropped them straight onto a denied page.
    for (const user of [USERS.admin, USERS.supervisor, USERS.clerk, USERS.operator]) {
      await login(page, user);
      await expect(page.getByTestId("privilege-denied"), `${user.username} was denied its landing page`).toHaveCount(0);
      await expect(page.getByRole("complementary", { name: "sidebar" })).toBeVisible();

      await page.getByRole("button", { name: "logout" }).click();
      await page.waitForURL(/\/login/);
    }
  });

  test("logout ends the session and protected routes stop rendering", async ({ page }) => {
    await login(page, USERS.admin);

    await page.getByRole("button", { name: "logout" }).click();
    await page.waitForURL(/\/en\/login/);

    // AuthGate must bounce a direct URL, not merely hide the nav.
    await page.goto("/en/inventory");
    await expect(page).toHaveURL(/\/en\/login/);
    await expect(page.getByTestId("inventory-table")).toHaveCount(0);
  });

  test("the flow is completable with the keyboard alone (Tab + Enter)", async ({ page }) => {
    await page.goto("/en/login");

    // Tab from the top of the document until focus lands in the username field, rather than
    // assuming a fixed number of stops — that would break the moment a link is added to the page.
    await page.locator("body").press("Tab");
    for (let i = 0; i < 10; i++) {
      const focused = await page.evaluate(() => document.activeElement?.id ?? "");
      if (focused === "username") break;
      await page.keyboard.press("Tab");
    }
    expect(await page.evaluate(() => document.activeElement?.id)).toBe("username");

    await page.keyboard.type(USERS.admin.username);
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.activeElement?.id)).toBe("password");

    await page.keyboard.type(USERS.admin.password);
    await page.keyboard.press("Enter");

    await page.waitForURL((url) => !url.pathname.endsWith("/login"));
    await expect(page.getByRole("complementary", { name: "sidebar" })).toBeVisible();
  });
});
