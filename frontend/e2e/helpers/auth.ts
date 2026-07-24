import { expect, type APIRequestContext, type Page } from "@playwright/test";

/**
 * Shared login / API-token helpers for the T21 end-to-end suite.
 *
 * Every spec needs a session, and before this existed each one carried its own private copy of
 * `login()`. One copy means a change to the login page is a one-line fix here rather than a hunt
 * across seven files.
 */

export const API = process.env.E2E_API_URL ?? "http://localhost:8000";

export interface Credentials {
  username: string;
  password: string;
}

/**
 * The seeded demo accounts, with the privileges that make each one interesting to a test. The
 * negative cases matter as much as the positive ones: a flow that only ever logs in as ADMIN cannot
 * tell "authorized" from "unguarded".
 *
 * These privilege sets are the ones the API actually returns, read back from
 * `POST /auth/login` — **not** the `ROLE_DEFINITIONS` literal in `seed_fake_data.py`. The two
 * disagree: migration `002_role_privilege_assignments` grants a wider set, and the seed script only
 * ever adds grants, never revokes them, so the effective set is the union of the two. Trusting the
 * seed script alone would have this suite asserting denials that do not happen.
 */
export const USERS = {
  /** company_admin — everything, including inventory.adjust, users.manage, audit.view. */
  admin: { username: "admin", password: "admin123" },
  /** production_supervisor — inventory.view + all work_orders.*; no receiving, users or audit. */
  supervisor: { username: "supervisor1", password: "demo123" },
  /** receiving_clerk — receiving + deliveries + inventory.view; no work_orders.view. */
  clerk: { username: "clerk1", password: "demo123" },
  /** machine_operator — `authenticated` and `work_orders.view` only. The most restricted account. */
  operator: { username: "operator1", password: "demo123" },
} as const satisfies Record<string, Credentials>;

/** A value that will not collide with earlier runs against the same (never-reset) database. */
export function unique(prefix: string): string {
  return `${prefix}${Date.now().toString().slice(-7)}`;
}

/** Log in through the real form and wait until the app has navigated away from /login. */
export async function login(
  page: Page,
  { username, password }: Credentials,
  locale = "en",
): Promise<void> {
  await page.goto(`/${locale}/login`);
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in|iniciar|login/i }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"));
}

/** A bearer token straight from the API, for setup and for asserting RBAC below the UI. */
export async function apiToken(
  request: APIRequestContext,
  { username, password }: Credentials,
): Promise<string> {
  const res = await request.post(`${API}/api/v1/auth/login`, {
    data: { username, password },
  });
  expect(res.status(), `login failed for ${username}`).toBe(200);
  return (await res.json()).access_token as string;
}

export const authHeaders = (token: string) => ({ Authorization: `Bearer ${token}` });

/**
 * Fail the test on an uncaught client-side exception or any 5xx response.
 *
 * Without this a spec can go green over a broken page: React swallows a render error into an empty
 * node, or a request 500s and the component just renders its empty state. Both look like success to
 * an `expect(...).toBeVisible()` on something else. Call this at the top of every test that drives
 * a page.
 */
export function failOnPageErrors(page: Page): void {
  page.on("pageerror", (error) => {
    throw new Error(`Uncaught page exception: ${error.message}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 500) {
      throw new Error(`Server error ${response.status()} from ${response.url()}`);
    }
  });
}
