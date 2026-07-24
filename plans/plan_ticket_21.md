# Plan — ACR-21 · T21 End-to-End Tests (Playwright)

**Ticket:** [ACR-21](https://linear.app/chronos-laboral/issue/ACR-21/t21-end-to-end-tests-playwright)
**Branch:** `ticket-21/e2e-tests-playwright` (from the ticket description, verbatim)
**Base:** `origin/master` @ `1ac2a7c`

> **Re-based mid-plan.** This plan was first drafted against `065e43b`. A `git fetch` immediately
> before cutting the worktree moved `origin/master` forward by two merges —
> `11aa86a` (ACR-27 reservations) and `1ac2a7c` (**ACR-18 work-orders UI**). Every finding below was
> re-verified against `1ac2a7c`; the entries marked **[re-verified]** changed as a result.
>
> **Second correction.** The initial exploration read the `wt-1` worktree, which is checked out on
> *local* `master` — **6 commits ahead of `origin/master`** with unmerged ACR-30 work. So the real
> base does **not** contain `frontend/e2e/ticket-30.spec.ts`, the production-worksheet
> router/service/migration, or migration `010_production_worksheets` (the `010` here is ACR-27's
> `010_stock_reservations`). `frontend/e2e/` holds **only** `ticket-19.spec.ts`; `backend/app/routers/`
> has `reservations.py` and no `production_worksheets.py`. `ticket-30.spec.ts` is still cited below as
> **prior art whose reasoning I follow**, but it is a file on an in-flight branch, not something this
> branch inherits or can re-run. Entries marked **[base-corrected]**.

## Goal (from the ticket)

Six Playwright flows against a running full stack (backend + Postgres + production frontend build),
giving a green gate before any release tag:

1. Authentication (+ keyboard-only, per the ticket's accessibility note)
2. Receiving a delivery → items appear in inventory
3. Work Order creation → allocate → in_production → completed → ready_for_shipment
4. Inventory trace & adjust
5. Language toggle & date locale (LR-007)
6. Mobile viewport, iPhone 14 (NFR-010)

Done condition: 6 test files, all green, and `npx playwright show-report` opens a report.

---

## Blocker status

`blockedBy`: ACR-15, ACR-16, ACR-17, ACR-18, ACR-19, ACR-20.

All are **Done** in Linear except **ACR-19**, which is still *In Progress* — but its PR (#24) is
already merged into `master` (`9f72293`), and `/users` + `/audit` are present and working on
`master`. The block is stale board state, not missing work. Confirmed at the approval gate.

**[re-verified]** ACR-18 was marked *Done* with an unmerged branch when this plan was drafted; the
`git fetch` before cutting the worktree brought `1ac2a7c feat(ACR-18): T18 — Work Orders Module UI
(#22)` onto `master`. That gap has closed on its own, and **Decision D1 was rewritten accordingly** —
Flow 3 is now a real click-path, not an API workaround.

---

## Current state

### Test harness — already exists, in good shape

- `frontend/playwright.config.ts:1` — `testDir: "./e2e"`, `fullyParallel: false`, `workers: 1`,
  `timeout: 30_000`, `baseURL` from `E2E_BASE_URL` (default `http://localhost:3000`),
  `trace: "retain-on-failure"`. Header comment already records KI-02: run against
  `npm run build && npm run start`, never `next dev`.
- `frontend/playwright.config.ts:12` — `reporter: [["list"]]` **only**. `npx playwright show-report`
  in the ticket's done-condition has nothing to open. → must add the `html` reporter.
- `frontend/playwright.config.ts:19-24` — a single `chromium` / Desktop Chrome project. No mobile
  device profile.
- `@playwright/test ^1.61.1` is in `frontend/package.json:36`. There is **no** `test` npm script;
  Jest runs via `npx jest`, Playwright via `npx playwright test`.
- `frontend/jest.config.ts:24` already excludes `<rootDir>/e2e/`, so new specs will not be swept
  into the Jest run.

### Existing specs — the patterns to imitate

- `frontend/e2e/ticket-19.spec.ts:16` — `login(page, username, password)` helper: `goto /en/login`,
  fill `#username` / `#password`, click `button[name=/sign in|iniciar|login/i]`, `waitForURL` off
  `/login`.
- `frontend/e2e/ticket-19.spec.ts:14` — collision-safe fixtures: `` `e2euser${Date.now()…}` `` so
  repeated runs against one database do not clash. Adopt this everywhere.
- `frontend/e2e/ticket-19.spec.ts:133-147` — the RBAC shape worth copying: assert the nav link is
  absent **and** that direct URL access hits `privilege-denied`, not merely hidden chrome.
- `frontend/e2e/ticket-30.spec.ts:34` — `apiToken(request, …)` via `POST /api/v1/auth/login`, then
  drive the backend with Playwright's `request` fixture.
- `frontend/e2e/ticket-30.spec.ts:5` — imports app code (`@/src/lib/qty`) rather than
  re-implementing it, precisely so the spec breaks when the app's formatter changes. Path aliases
  work in specs.
- `frontend/e2e/ticket-30.spec.ts:50-75` — `GET /inventory` applies **no `ORDER BY`**
  (`inventory_service._build_lot_query`), so a single page is not a stable window; the helper pages
  through everything. Any inventory assertion in this ticket must do the same.
- `frontend/e2e/ticket-30.spec.ts:7-16` — the precedent for a feature with no UI of its own: drive
  it over the API, then assert **the consequence a user can actually see**.

**[base-corrected]** Of the two, only `ticket-19.spec.ts` is actually on this branch's base —
`ticket-30.spec.ts` lives on the unmerged ACR-30 branch. Its reasoning is still the right model to
copy (drive setup over the API, page through unordered endpoints, import the app's own formatter
instead of re-implementing it), and I re-verified the fact it rests on: `_build_lot_query`
(`backend/app/services/inventory_service.py:28-42`) applies **no `ORDER BY`**. But the `allLots`
helper must be **written fresh here**, not "lifted", and D5's migration has only one spec to migrate.

### Seed data

- `scripts/reset-db-and-seed.sh` — wipes the Docker volume, `alembic upgrade head`, then
  `backend/scripts/seed_fake_data.py`.
- Users (`backend/scripts/seed_fake_data.py:105-142`): `admin`/`admin123` (company_admin),
  `supervisor1`, `clerk1`, `operator1`, `operator2`, all `demo123`.
- Role privileges (`seed_fake_data.py:52-101`):
  - `company_admin` — everything incl. `inventory.adjust`, all `work_orders.*`, `users.manage`, `audit.view`
  - `receiving_clerk` — `receiving.view`, `deliveries.create`, `deliveries.view` (**no** `inventory.view`)
  - `production_supervisor` — `inventory.view` + all `work_orders.*`
  - `machine_operator` — `authenticated`, `work_orders.view` only
- `WORK_ORDER_SEEDS` at `seed_fake_data.py:215` — work orders and materials are already seeded.
- ⚠️ The ticket's done-condition names `backend/scripts/seed_test_data.py`. **That file does not
  exist.** The repo's seeder is `seed_fake_data.py`, invoked through `./scripts/reset-db-and-seed.sh`.
  Use the real one; do not create a duplicate script (Decision D3).

### Application surface on `master`

| Route | State |
|---|---|
| `/[locale]/login` | real — `AuthForm.tsx:74,92,103` (`#username`, `#password`, submit) |
| `/[locale]/dashboard` | real |
| `/[locale]/receiving` | real — `ReceivingView` = OCRUploader + NewDeliveryForm + DeliveryList |
| `/[locale]/inventory` | real — table, filters, adjust/location/split/log modals |
| `/[locale]/users`, `/audit` | real (ACR-19, merged) |
| `/[locale]/work-orders` | **real [re-verified]** — `page.tsx` renders `<WorkOrders />`; all six ACR-18 components present |
| `/[locale]/shipping` | present but nav-hidden and privilege-starved (that is ACR-35) |

- **[re-verified]** `frontend/src/components/work-orders/` now holds `WorkOrders.tsx`,
  `WorkOrderList.tsx`, `WorkOrderDetail.tsx`, `CreateWorkOrderForm.tsx`,
  `AllocateMaterialsModal.tsx`, `AssignLineDropdown.tsx`, `PriorityReorder.tsx` + `types.ts` /
  `constants.ts`. `WorkOrders.tsx:23` groups by the five statuses and gates the create button on
  `WORK_ORDERS_CREATE`; `WorkOrderList.tsx:21` exposes `data-testid={`wo-row-${wo.id}`}`.
- **[re-verified]** `frontend/components/ui/sheet.tsx` now exists on `master` (ACR-18 added it), so
  Q1's mobile drawer needs **no** `npx shadcn add sheet`.
- **[re-verified]** `frontend/src/lib/privileges.ts` now defines `WORK_ORDERS_VIEW`,
  `WORK_ORDERS_CREATE`, `WORK_ORDERS_ALLOCATE`, `WORK_ORDERS_ASSIGN`, `WORK_ORDERS_STATUS`,
  `WORK_ORDERS_SEQUENCE`, `SHIPPING_VIEW`, `SHIPPING_CREATE`.
- ⚠️ `frontend/src/components/layout/NavSidebar.tsx:30-31` — the `workOrders` and `shippingNav`
  entries are **still commented out**, and the commented `workOrders` line still names the *wrong*
  privilege (`PRIVILEGES.RECEIVING_VIEW`). So ACR-18 shipped a module that is reachable only by
  typing the URL. See gap **G5**.
- The **backend** work-order API is complete and merged — `backend/app/routers/work_orders.py`:
  `POST ""` (`work_orders.create`), `GET ""`/`GET /{id}` (`work_orders.view`),
  `PATCH /{id}/assign`, `/status`, `/sequence`, `/allocate` (one privilege each).

### Gaps found against the acceptance criteria

- **~~G1 — no work-order UI on `master`~~ [re-verified: CLOSED]** by `1ac2a7c`. Flow 3 is a real
  click-path.
- **G5 — the Work Orders nav entry is commented out** (`NavSidebar.tsx:30`), so a supervisor can only
  reach their own module by typing `/en/work-orders`. Uncommenting it with the now-correct
  `PRIVILEGES.WORK_ORDERS_VIEW` is a one-line fix and is required by Flow 6's wording
  ("receiving + WO + inventory all usable"). The adjacent `shippingNav` line stays commented —
  that one is ACR-35's, and its privileges are still granted to no role.
- **G2 — receiving components carry zero `data-testid`s.** `grep` over
  `src/components/receiving/*.tsx` returns nothing, while inventory
  (`InventoryTable.tsx:60,67,104…`) and users are thoroughly instrumented. Flow 2 needs hooks.
- **G3 — dates are not locale-aware.** `AuditLogTable.tsx:17-19` uses
  `new Date(value).toLocaleString()` and `TransactionLogModal.tsx:100` the same, both with **no
  locale argument** — they follow the *browser's* locale, not the app's. `DeliveryList.tsx:126`
  renders `delivery_date` as a raw string. So toggling EN→ES changes nav labels but **not** date
  format, and Flow 5 / LR-007 fails as specified. There is no date helper in `src/lib/`
  (`api-client.ts`, `auth-*.ts`, `privileges.ts`, `qty.ts` only).
- **G4 — the layout has no mobile treatment.** `AppShell.tsx:17` hard-codes `ml-64` and
  `NavSidebar.tsx:69` is `fixed inset-y-0 left-0 … w-64` with **no breakpoint**. At the iPhone 14's
  390 px viewport, 256 px of that is sidebar and content is crushed into ~134 px — Flow 6's "no
  overflow, all usable" will fail. See Open question **Q1**; this is the one decision I cannot make
  from the codebase.

### Schema / migration impact

**None.** No models, no endpoints, no privileges, no Alembic revision. The latest revision is
`010_production_worksheets.py` and this ticket does not add `011`.

---

## Decisions taken (resolvable from existing patterns — recorded, not escalated)

- **D1 [rewritten after the re-base] — Flow 3 is a real click-path through the ACR-18 UI.**
  The original decision (drive it over the API, per `ticket-30.spec.ts`'s precedent for a UI-less
  feature) existed only to work around `/work-orders` being a placeholder. `1ac2a7c` landed the
  module, so that workaround is obsolete and would now under-test the ticket: Flow 3 is worded as a
  *user* journey. The spec drives create → assign → allocate → status walk through the components,
  and uses the `request` fixture only for (a) reading exact expected stock values, since
  `GET /inventory` is unordered, and (b) asserting RBAC at the API, which the UI cannot prove.
- **D2 — fix the date-locale defect rather than assert the broken behaviour.** G3 is a real defect
  against a stated requirement (LR-007), and catching precisely this is why the ticket exists. Add
  `src/lib/datetime.ts` and route the three call sites through it. Small, contained, and it follows
  `qty.ts` — an existing single-purpose formatting module the specs already import.
- **D3 — use `./scripts/reset-db-and-seed.sh` + `seed_fake_data.py`,** not the non-existent
  `seed_test_data.py` the done-condition names. Record the discrepancy in the PR body.
- **D4 — six spec files, flat, `ticket-21-*.spec.ts`.** Satisfies the done-condition's "6 test files"
  while matching the existing flat `ticket-NN.spec.ts` convention in `e2e/`.
- **D5 — extract the shared `login`/`apiToken` helper** into `e2e/helpers/`. Three copies would
  otherwise exist. Migrate `ticket-19.spec.ts` and `ticket-30.spec.ts` onto it **only after** the new
  suite is green, and re-run both to prove the migration.

---

## Change list

### CREATE

| File | Purpose |
|---|---|
| `frontend/e2e/helpers/auth.ts` | `USERS` constants, `login(page, user)`, `apiToken(request, user)`, `unique(prefix)` |
| `frontend/e2e/helpers/inventory.ts` | `allLots()` paging helper + `inStorageTotal()` — written fresh; `_build_lot_query` has no `ORDER BY`, so paging is mandatory |
| `frontend/e2e/ticket-21-auth.spec.ts` | Flow 1 — auth, session persistence, logout, keyboard-only |
| `frontend/e2e/ticket-21-receiving.spec.ts` | Flow 2 — delivery intake → inventory |
| `frontend/e2e/ticket-21-work-orders.spec.ts` | Flow 3 — WO lifecycle (D1) |
| `frontend/e2e/ticket-21-inventory.spec.ts` | Flow 4 — trace & adjust |
| `frontend/e2e/ticket-21-locale.spec.ts` | Flow 5 — EN/ES toggle + date locale (LR-007) |
| `frontend/e2e/ticket-21-mobile.spec.ts` | Flow 6 — iPhone 14 viewport (NFR-010) |
| `frontend/e2e/README.md` | How to bring the stack up and run the suite |
| `frontend/src/lib/datetime.ts` | `formatDate(value, locale)` / `formatDateTime(value, locale)`, invalid input passed through unchanged (mirrors `AuditLogTable`'s current `Number.isNaN` guard) |
| `frontend/src/lib/__tests__/datetime.test.ts` | Jest — en vs es output, invalid/empty passthrough, ISO-date-only input |

### MODIFY

| File | Change |
|---|---|
| `frontend/playwright.config.ts` | add `["html", { open: "never" }]` to `reporter` so `show-report` works; add the iPhone 14 device profile for Flow 6 |
| `frontend/src/components/audit/AuditLogTable.tsx` | `formatTimestamp` → `formatDateTime(value, locale)` via `useLocale()` |
| `frontend/src/components/inventory/TransactionLogModal.tsx` | `:100` → `formatDateTime(...)` |
| `frontend/src/components/receiving/DeliveryList.tsx` | `:126`, `:184` → `formatDate(...)`; `:196` → `formatDateTime(...)`; add `data-testid`s (`delivery-table`, `delivery-row-{id}`, `delivery-search`, `delivery-detail`) |
| `frontend/src/components/receiving/NewDeliveryForm.tsx` | add `data-testid`s (`delivery-form`, `bol-input`, `delivery-date-input`, `carrier-combobox`, `provider-combobox`, `quantity-{i}`, `add-item`, `submit-delivery`, `delivery-error`) |
| `frontend/src/components/receiving/OCRUploader.tsx` | `data-testid="ocr-dropzone"` |
| `frontend/src/components/layout/NavSidebar.tsx` | **G5** — uncomment the `workOrders` entry with `PRIVILEGES.WORK_ORDERS_VIEW` (the commented line names `RECEIVING_VIEW`, which is wrong); leave `shippingNav` commented for ACR-35. Plus the `md:` breakpoint from Q1 |
| `frontend/src/components/layout/AppShell.tsx` | Q1 — `ml-64` → `md:ml-64` |
| `frontend/src/components/{audit,inventory,receiving}/__tests__/*.test.tsx` | update only where an assertion pins the old date output |
| `frontend/src/components/layout/__tests__/*.test.tsx` | nav test now expects the Work Orders link for privileged roles and its absence for `clerk1` |

**Also CREATE for Q1:** `frontend/src/components/layout/MobileNav.tsx` +
`frontend/src/components/layout/__tests__/MobileNav.test.tsx`.
`frontend/components/ui/sheet.tsx` is **already on `master`** as of `1ac2a7c` — no shadcn install.

---

## Data / API

Nothing new. No models, no migrations, no endpoints, no privileges. Existing contracts used:

- `POST /api/v1/auth/login` → `{ access_token }`
- `POST /api/v1/deliveries`, `GET /api/v1/deliveries`
- `GET /api/v1/inventory?page&page_size` → `{ total, results[] }` (**unordered**)
- `POST /api/v1/work-orders` · `PATCH /{id}/assign|/status|/sequence|/allocate`
- `PATCH /api/v1/users/me` `{ preferred_language }` (the language toggle already calls this,
  `NavSidebar.tsx:55`)

---

## Test plan

### Flow 1 — Authentication (`ticket-21-auth.spec.ts`)
- wrong password → error surfaces, URL stays on `/login`
- unknown username → same treatment, no stack trace / 500
- empty submit → blocked, no network call
- `admin`/`admin123` → leaves `/login`, sidebar renders, user chip shows the full name
- reload mid-session → still authenticated (cookie survives)
- logout → back at `/login`; a direct `goto /en/dashboard` afterwards does not render the app shell
- **keyboard-only:** `Tab` to username → type → `Tab` → type → `Enter` submits → authenticated
  (the ticket's explicit accessibility requirement)

### Flow 2 — Receiving (`ticket-21-receiving.spec.ts`)
- login `clerk1`; `/en/receiving`
- create a delivery with a run-unique BOL reference: carrier + provider via `CreatableCombobox`
  (exercising the **inline-create** path), delivery date, one item with quantity/pallets/units
- it appears in `DeliveryList`; opening it shows the same values
- **validation:** empty submit blocked; whitespace-only BOL rejected; quantity `0` and a negative
  quantity rejected; double-submit does not create two deliveries
- **consequence:** an `admin` session on `/en/inventory` sees the received quantity — cross-checked
  against `allLots()` for exactness, since the list is unordered
- **RBAC:** `operator1` on `/en/receiving` → `privilege-denied`, and `POST /deliveries` with that
  token → 403 (blocked, not merely hidden)

### Flow 3 — Work Order lifecycle (`ticket-21-work-orders.spec.ts`) — D1
- login `admin`; reach `/work-orders` **from the nav link** (proving G5's fix), not by typed URL
- "Create Work Order" → `CreateWorkOrderForm`: product, quantity, priority, target date, materials →
  submit → the new `wo-row-{id}` appears under the **Created** group
- open it → `WorkOrderDetail` → assign a production line via `AssignLineDropdown`
- allocate via `AllocateMaterialsModal` → the row moves to **Materials Allocated**
- walk the status control `in_production` → `completed` → `ready_for_shipment`, asserting the row
  lands in the matching collapsible group each time
- **validation:** quantity `0` and negative are refused; submitting with no materials is refused;
  allocating a second time does not double-deduct stock
- **consequence:** the lot(s) the allocation touched render their new on-hand on `/en/inventory`
  (expected values read via the API's `allLots()`, never hard-coded)
- **operator scoping:** `operator1` sees only `in_production` work orders
  (`WorkOrders.tsx:38`) and gets no create button
- **RBAC at the API, not just the UI:** `operator1` → `POST /work-orders` 403,
  `PATCH /{id}/allocate` 403; `clerk1` (no `work_orders.view`) → `GET /work-orders` 403 and
  `privilege-denied` on the page

### Flow 4 — Inventory trace & adjust (`ticket-21-inventory.spec.ts`)
- admin → `/en/inventory`; `inventory-table` visible
- row click → `inventory-details-dialog` (traceability) shows lot number, product, source
- `log-btn-{id}` → `TransactionLogModal` lists movements
- `adjust-btn-{id}` → `adjust-modal` → new quantity + reason → `confirm-adjust` → the row shows the
  new value, and `GET /inventory` agrees
- **validation:** negative quantity, non-numeric, and empty reason each surface `adjust-error` and
  leave the quantity untouched
- filters: `search-input` narrows the table; `clear-filters` restores it
- **RBAC:** `clerk1` → `/en/inventory` renders `privilege-denied`; `PATCH` adjust with that token → 403

### Flow 5 — Language & date locale (`ticket-21-locale.spec.ts`) — LR-007
- admin on `/en/…`; nav reads "Inventory"
- click `aria-label="toggle-language"` → URL becomes `/es/…`, nav reads "Inventario"
- **date format changes:** the same delivery row renders `M/D/YYYY` under `/en` and `D/M/YYYY` under
  `/es`; likewise the audit timestamp. *(Fails on `master` — fixed by D2.)*
- reload → still Spanish and still `/es` (persisted through `PATCH /users/me`)
- toggle back to EN → restored
- the spec imports `formatDate` from `@/src/lib/datetime` rather than hard-coding expected strings,
  following `ticket-30.spec.ts:5`'s reasoning

### Flow 6 — Mobile viewport (`ticket-21-mobile.spec.ts`) — NFR-010
- `test.use({ ...devices["iPhone 14"] })`
- for `/receiving`, `/inventory`, `/work-orders`: assert
  `document.documentElement.scrollWidth <= window.innerWidth + 1` (no horizontal overflow) and that
  the primary control of each page is visible and clickable
- **This is the flow that currently cannot pass — see Q1.**

### Cross-cutting, every spec
- fail the test on any uncaught page error or any `>= 500` response, via `page.on("pageerror")` and
  `page.on("response")` listeners in the shared helper — the skill's "a 500 is a failure even if the
  UI looks fine", enforced by the suite rather than by my eyeballs.

### Regression gate (unchanged suites must stay green)
- `pytest` — no backend change, so this is purely a no-regression run; no new `app.*` module, so the
  85% floor is unaffected
- `npx jest` — plus the new `datetime.test.ts`
- `npm run lint`, `npm run build`, `./scripts/smoke-test.sh`
- `npx playwright test` — all 6 new files **and** the 1 pre-existing one (`ticket-19.spec.ts`)

---

## Live verification (browser, by hand)

1. `./scripts/reset-db-and-seed.sh`, backend on `:8000`, `npm run build && npm run start` on `:3000`.
2. Log in wrong → right → reload → logout, keyboard-only for one pass.
3. Receive a delivery as `clerk1` with inline-created carrier and provider; confirm the lot on
   `/inventory` as `admin`.
4. Adjust a lot, open its traceability and transaction log; try a negative quantity and an empty
   reason.
5. Toggle EN↔ES on `/receiving` and `/audit`; confirm nav labels **and** dates both change; reload.
6. Resize to 390×844 and walk receiving → inventory → work-orders looking for overflow.
7. Repeat the privilege-denied paths as `clerk1` and `operator1`, watching the network panel for the
   403 (not just the hidden nav).
8. Both themes on any page the date change touches.

---

## Risks / open questions

### Q1 — RESOLVED: ACR-21 also builds mobile navigation

Flow 6 was not a test-authoring problem, it was a missing feature. `AppShell.tsx:17` hard-codes
`ml-64` and `NavSidebar.tsx:69` is `fixed … w-64` with no breakpoint, so at 390 px the sidebar eats
256 px and content overflows. No amount of test-writing makes that green.

**Decision (user, at the plan gate): fix it inside ACR-21.** Below `md`, hide the fixed sidebar and
drop the margin; add a `md:hidden` top bar whose hamburger opens the same nav in a `Sheet`:

```diff
// AppShell.tsx
-  <div className={cn("flex flex-1 flex-col", hasSidebar && "ml-64")}>
+  <div className={cn("flex flex-1 flex-col", hasSidebar && "md:ml-64")}>

// NavSidebar.tsx
-  className="fixed inset-y-0 left-0 z-30 flex w-64 …"
+  className="fixed inset-y-0 left-0 z-30 hidden w-64 md:flex …"
```

Plus a new `MobileNav.tsx` reusing the same `NAV_ITEMS` + `hasPrivilege` filter, so the mobile and
desktop navs cannot drift apart. **[re-verified]** `frontend/components/ui/sheet.tsx` arrived with
ACR-18 in `1ac2a7c`, so the `npx shadcn add sheet` step this plan originally called for is no longer
needed.

**Consequences folded into the rest of this plan:**
- Additional CREATE: `frontend/src/components/layout/MobileNav.tsx`,
  `frontend/src/components/layout/__tests__/MobileNav.test.tsx`.
- Additional MODIFY: `frontend/src/components/layout/AppShell.tsx`,
  `frontend/src/components/layout/NavSidebar.tsx`.
- The privilege filter must be asserted on mobile too: a `clerk1` session must not see Users/Audit in
  the drawer. Otherwise the drawer becomes a privilege-leak surface the desktop nav does not have.
- Desktop layout must be proven unchanged at ≥ `md` — the existing specs re-run at Desktop Chrome
  cover this.

### Non-blocking risks
- **~~R1 — ACR-18 board hygiene~~ [re-verified: CLOSED].** ACR-18's branch merged as `1ac2a7c`
  before work started, so `master` and the board now agree.
- **R7 — ACR-18's UI breaks two `CLAUDE.md` conventions**, found while re-planning Flow 3:
  `WorkOrders.tsx:66,70` hard-code the English strings "Work Orders" / "Create Work Order" instead of
  using `useTranslations`, and `WorkOrderList.tsx:19` hard-codes `bg-white`, which is wrong in the
  default dark theme. Both are pre-existing and **out of scope** — I am not silently fixing another
  ticket's work inside a test ticket. Two consequences I *will* handle: Flow 5 asserts locale
  switching on `/receiving` and `/audit` rather than `/work-orders` (which cannot pass), and I will
  raise these in the final report so they can be ticketed.
- **R2 — seeded-data coupling.** Specs must not assume a fresh database (the flows mutate stock).
  Mitigation: derive expected values from a pre-read via the API, never from literals — the
  `ticket-30.spec.ts` approach — and suffix all created records with `Date.now()`.
- **R3 — `GET /inventory` has no `ORDER BY`.** Page-1 assertions would be flaky. Mitigated by the
  shared `allLots()` helper; this is a footgun for anyone adding inventory assertions later, so it is
  documented in `e2e/README.md`.
- **R4 — CI.** The suite needs a full stack (Postgres + backend + built frontend) that
  `.github/workflows/ci.yml` does not stand up today. Treating CI wiring as **out of scope** and
  documenting the local invocation instead; say so in the PR rather than silently leaving it.
- **R5 — D5's helper migration** could break the two existing specs. Sequenced last and gated on a
  full green re-run.
- **R6 — the language toggle does a full `window.location` navigation** (`NavSidebar.tsx:57`), so
  Flow 5 must `waitForURL` rather than assume client-side routing.

---

## Build order

1. `e2e/helpers/auth.ts` + `helpers/inventory.ts`; `playwright.config.ts` — html reporter + iPhone 14
   profile. Prove the harness with a trivial run.
2. **Flow 1** (`ticket-21-auth.spec.ts`) — no app changes needed. Green first.
3. **Flow 4** (`ticket-21-inventory.spec.ts`) — testids already exist. Green second.
4. **G2:** add receiving `data-testid`s, then **Flow 2** (`ticket-21-receiving.spec.ts`).
5. **G5:** uncomment the Work Orders nav entry with the correct privilege; then **Flow 3**
   (`ticket-21-work-orders.spec.ts`) per D1, adding `data-testid`s to the ACR-18 components where
   the click-path needs hooks they do not yet expose.
6. **D2/G3:** write **Flow 5** first and watch the date assertion fail; then add
   `src/lib/datetime.ts` + its Jest test, route the three call sites through it, fix any Jest
   assertions pinned to the old output, and watch Flow 5 go green.
7. **Flow 6** — write `ticket-21-mobile.spec.ts` first and watch the overflow assertion fail; then
   add `MobileNav.tsx` + its Jest test (reusing the on-`master` `sheet.tsx`), apply the
   `AppShell`/`NavSidebar` breakpoint changes, and watch it go green. Re-run the desktop specs to
   prove ≥ `md` is untouched.
8. `e2e/README.md`.
9. **D5 [base-corrected]:** migrate `ticket-19.spec.ts` onto the shared helper (it is the only
   pre-existing spec on this base); re-run all 7 spec files.
10. Full gate: `pytest` · `npx jest` · `npm run lint` · `npm run build` · `./scripts/smoke-test.sh` ·
    `npx playwright test` · `npx playwright show-report`.
