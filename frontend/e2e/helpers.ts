import { APIRequestContext, Page, expect } from "@playwright/test";

/**
 * Shared e2e scaffolding.
 *
 * `login`, the demo credentials, and the API base URL were copied verbatim into each spec until
 * there were three of them; the login selectors are a UI contract, so a change to the login form
 * should break one file, not every spec.
 */

/** The backend, which is a different origin from the frontend `baseURL`. */
export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";

/** Seeded by backend/scripts/seed_fake_data.py. */
export const USERS = {
  admin: { username: "admin", password: "admin123" },
  clerk: { username: "clerk1", password: "demo123" },
  supervisor: { username: "supervisor1", password: "demo123" },
  operator: { username: "operator1", password: "demo123" },
} as const;

export async function login(page: Page, username: string, password: string) {
  await page.goto("/en/login");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: /sign in|iniciar|login/i }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"));
}

/** A bearer token straight from the API, for asserting server-side enforcement. */
export async function apiToken(
  request: APIRequestContext,
  username: string,
  password: string,
): Promise<string> {
  const resp = await request.post(`${API_URL}/api/v1/auth/login`, {
    data: { username, password },
  });
  expect(resp.ok()).toBeTruthy();
  return (await resp.json()).access_token;
}
