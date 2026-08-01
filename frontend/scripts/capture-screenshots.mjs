/**
 * ACRA MES — scripted screenshot capture for the evidence package.
 *
 * RU-08's named failure mode is "screenshots of outputs presented without controlled testing
 * conditions". A folder of hand-taken screenshots is exactly that: nobody can tell which build,
 * which data, or which viewport produced them, and they cannot be regenerated. So this is a
 * script, not a photo session — same seeded fixture, same viewport, same login as the e2e suite,
 * and a MANIFEST recording the conditions.
 *
 * Reuses the login selectors from `frontend/e2e/helpers.ts` rather than re-deriving them: they are
 * a UI contract, and a change to the login form should break one file, not two.
 *
 * Usage (from repo root, with the stack up and the scale-1 fixture seeded):
 *   node frontend/scripts/capture-screenshots.mjs [OUTPUT_DIR]
 *
 * Env: E2E_BASE_URL (default http://localhost:3000), E2E_API_URL (default http://localhost:8000)
 */
import { chromium } from "@playwright/test";
import { execSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const OUT = resolve(process.argv[2] ?? "validation-evidence/screenshots");
const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const API = process.env.E2E_API_URL ?? "http://localhost:8000";
const USER = { username: "admin", password: "admin123" }; // seeded by seed_fake_data.py

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 390, height: 844 }; // iPhone 14 — the viewport NFR-010 is tested at

/** Journey order, so the sequence reads as the operator flow the system implements. */
const SHOTS = [
  { name: "02_dashboard", path: "/en/dashboard", waitFor: "h1" },
  { name: "03_receiving", path: "/en/receiving", waitFor: "h1" },
  { name: "04_inventory", path: "/en/inventory", waitFor: "table, h1" },
  { name: "05_work_orders", path: "/en/work-orders", waitFor: "h1" },
  { name: "06_shipping", path: "/en/shipping", waitFor: "h1" },
  { name: "07_delivery_notes", path: "/en/delivery-notes", waitFor: "h1" },
  { name: "08_audit_log", path: "/en/audit", waitFor: "h1" },
  { name: "09_master_data_contacts", path: "/en/master-data/contacts", waitFor: "h1" },
];

const sha = (() => {
  try {
    return execSync("git rev-parse --short HEAD", { encoding: "utf8" }).trim();
  } catch {
    return "unknown";
  }
})();

/** Settle animations and lazy content so two runs of this script produce comparable images. */
async function settle(page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(400);
}

const captured = [];

async function shoot(page, name, note) {
  const file = join(OUT, `${name}.png`);
  await settle(page);
  await page.screenshot({ path: file, fullPage: false });
  captured.push({ name, note });
  console.log(`  captured ${name}.png — ${note}`);
}

const browser = await chromium.launch();
try {
  mkdirSync(OUT, { recursive: true });
  const ctx = await browser.newContext({ viewport: DESKTOP, deviceScaleFactor: 2 });
  const page = await ctx.newPage();

  // --- 01 login, before authenticating -------------------------------------
  await page.goto(`${BASE}/en/login`);
  await shoot(page, "01_login", "unauthenticated entry point (C-01)");

  // --- authenticate, using the e2e suite's selectors ------------------------
  await page.locator("#username").fill(USER.username);
  await page.locator("#password").fill(USER.password);
  await page.getByRole("button", { name: /sign in|iniciar|login/i }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 20000 });

  for (const s of SHOTS) {
    await page.goto(`${BASE}${s.path}`);
    await page.waitForSelector(s.waitFor, { timeout: 15000 }).catch(() => {});
    await shoot(page, s.name, `${s.path} as admin`);
  }

  // --- 10 Spanish locale — the bilingual claim, shown rather than asserted --
  await page.goto(`${BASE}/es/inventory`);
  await page.waitForSelector("h1", { timeout: 15000 }).catch(() => {});
  await shoot(page, "10_locale_es_inventory", "same surface under /es (C-10)");

  // --- 11 mobile viewport — NFR-010 ----------------------------------------
  const mctx = await browser.newContext({ viewport: MOBILE, deviceScaleFactor: 2 });
  const mpage = await mctx.newPage();
  await mpage.goto(`${BASE}/en/login`);
  await mpage.locator("#username").fill(USER.username);
  await mpage.locator("#password").fill(USER.password);
  await mpage.getByRole("button", { name: /sign in|iniciar|login/i }).click();
  await mpage.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 20000 });
  await mpage.goto(`${BASE}/en/inventory`);
  await mpage.waitForSelector("h1", { timeout: 15000 }).catch(() => {});
  await shoot(mpage, "11_mobile_inventory", "390x844 viewport (NFR-010)");
  await mctx.close();

  // --- 12 OpenAPI surface ---------------------------------------------------
  await page.goto(`${API}/docs`);
  await page.waitForSelector(".swagger-ui", { timeout: 15000 }).catch(() => {});
  await shoot(page, "12_api_docs", "FastAPI OpenAPI UI — the 62-route surface");

  // --- provenance -----------------------------------------------------------
  const manifest = [
    "# Screenshot Manifest",
    "",
    "Produced by `frontend/scripts/capture-screenshots.mjs` — **not taken by hand.** Re-running the",
    "script against the same seeded fixture regenerates every image below.",
    "",
    `- **Captured:** ${new Date().toISOString()}`,
    `- **Repo:** acra_dev @ ${sha}`,
    `- **Frontend:** ${BASE} · **Backend:** ${API}`,
    `- **Fixture:** seed_fake_data.py scale 1 (the deterministic demo fixture the e2e suite assumes)`,
    `- **User:** ${USER.username} (company_admin — full privilege union, so no surface is hidden)`,
    `- **Viewport:** ${DESKTOP.width}x${DESKTOP.height} @2x, except \`11_mobile_*\` at ${MOBILE.width}x${MOBILE.height} @2x`,
    "",
    "| File | What it shows |",
    "|---|---|",
    ...captured.map((c) => `| \`${c.name}.png\` | ${c.note} |`),
    "",
    "**Read these as surface evidence, not performance evidence.** They show that the components in",
    "§02's table exist and render against real seeded data. Every measured claim in §04–§06 comes from",
    "the benchmark artifacts, never from an image.",
    "",
  ].join("\n");
  writeFileSync(join(OUT, "MANIFEST.md"), manifest, "utf8");

  console.log(`\n${captured.length} screenshots + MANIFEST.md written to ${OUT}`);
} finally {
  await browser.close();
}
