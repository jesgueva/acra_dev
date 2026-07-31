# End-to-end tests

Playwright specs that drive the real stack: Postgres, the FastAPI backend, and a **production**
Next.js build. They are not run by `npx jest` — `jest.config.ts` excludes this directory.

## Running them

```bash
# 1. Database: migrations + seed data (wipes the volume)
#    Run it with NO arguments — these specs assert against the scale-1 demo fixture, and
#    `--scale`/`--materials` change the rows they read.
./scripts/reset-db-and-seed.sh

# 2. Backend
cd backend && uvicorn app.main:app --port 8000

# 3. Frontend — a production build, NOT `next dev` (it panics; see KI-02)
cd frontend && npm run build && npm run start

# 4. The suite
cd frontend && npx playwright test
npx playwright show-report        # the html reporter is enabled by default
```

First run only: `npx playwright install chromium`.

### Running against a different stack

Both the frontend and backend URLs are overridable, which matters when the default ports are taken
by another worktree:

```bash
E2E_BASE_URL=http://localhost:3200 E2E_API_URL=http://localhost:8200 npx playwright test
```

The backend must be told to accept that frontend origin, or every browser request is CORS-blocked
and the pages render empty:

```bash
# backend/.env
CORS_ORIGINS=http://localhost:3000,http://localhost:3200
```

## Layout

| File | Flow |
|---|---|
| `helpers/auth.ts` | Seeded users, `login`, `apiToken`, and `failOnPageErrors` |
| `helpers/inventory.ts` | Reading stock levels across pages |
| `ticket-21-auth.spec.ts` | 1 — authentication, incl. keyboard-only (UC-011) |
| `ticket-21-receiving.spec.ts` | 2 — receiving a delivery → inventory (UC-001, manual path / A1) |
| `ticket-21-work-orders.spec.ts` | 3 — work-order lifecycle (UC-003, UC-004) |
| `ticket-21-inventory.spec.ts` | 4 — traceability & adjustment (UC-002) |
| `ticket-21-locale.spec.ts` | 5 — language toggle & date locale (LR-007) |
| `ticket-21-mobile.spec.ts` | 6 — iPhone 14 viewport (NFR-010) |
| `ticket-21-ocr.spec.ts` | 7 — OCR-assisted receiving, **stubbed** (UC-001 steps 3–6, E1; FR-002/003) |
| `ticket-21-production-planning.spec.ts` | 8 — plan & prioritize daily production (UC-005; FR-015/017/021) |
| `ticket-19.spec.ts` | User management & audit (UC-009, incl. E1/E2) |

### SRS coverage and its two holes

Every use case in SRS v2.1 §5 is covered. Two of them only partly, and deliberately:

- **UC-001 steps 3–5 are stubbed, not live.** `POST /deliveries/ocr` hands the image to
  Gemini/Anthropic. Flow 7 intercepts it at the network boundary and asserts the contract the UI
  depends on — populate, correct, confirm — because a live call needs API keys, costs money per
  run, and fails on model variance. Extraction *quality* is ACR-36's job, not this suite's.
- **UC-005 step 3 has no UI to drive.** `PriorityReorder.tsx` and
  `PATCH /work-orders/{id}/sequence` both exist, but no page mounts the component, so the sequence
  tests go straight to the API. When the control is wired up, the contract is already pinned.

Not covered, because the backend does not implement it: **UC-003 E2** (warn on a duplicate work
order) has no check in `work_order_service`.

Two projects are configured: `chromium` runs everything at desktop size, and `mobile` runs only
`ticket-21-mobile.spec.ts` at iPhone 14 dimensions. Select one with `--project=mobile`.

## Writing more of them

A few things this suite learned the hard way:

- **Never hard-code a quantity.** The database is not reset between runs and these flows move
  stock, so read the value from the API first and assert relative to it.
- **Do not assume a row is on page 1.** `GET /inventory` used to have no `ORDER BY` at all, so
  `LIMIT/OFFSET` paging could return a row twice and skip another — `allLots()` collected every
  page and still came back short once the table outgrew 100 rows. That is fixed at source now
  (`_build_lot_query` orders by lot id), but the habit stands: read the set through
  `allLots()` and filter it, rather than trusting the first page. The same trap applies to
  `/delivery-notes`, which pages at 20 ordered by `document_date DESC` — see `RUN_DATE` in
  `ticket-39.spec.ts` for how that spec keeps its own rows findable.
- **Scope nav lookups to the sidebar.** The dashboard's quick-action bar links to the same modules,
  so a bare `getByRole("link", { name: "Users" })` matches twice.
- **Call `failOnPageErrors(page)`.** Without it a spec can pass over a broken page: React swallows a
  render error into an empty node and a 500 just leaves a component in its empty state, both of
  which look fine to an assertion about something else. It caught two real crashes here.
- **Import the app's own formatters** (`@/src/lib/qty`, `@/src/lib/datetime`) instead of
  re-implementing them, so a formatting change fails the test rather than silently diverging.
- **Prove permissions at the API too.** A hidden button is not a permission; assert the endpoint
  returns 403 for the token as well.

## Seeded accounts

`backend/scripts/seed_fake_data.py`. Effective privileges are the union of migration
`002_role_privilege_assignments` and the seed script — the script only ever adds grants, never
revokes — so read them from `POST /auth/login` rather than from `ROLE_DEFINITIONS`.

| User | Password | Notable privileges |
|---|---|---|
| `admin` | `admin123` | everything |
| `supervisor1` | `demo123` | `inventory.view`, all `work_orders.*` — **no** `inventory.adjust` |
| `clerk1` | `demo123` | receiving, deliveries, `inventory.view` — **no** `work_orders.view` |
| `operator1` | `demo123` | `work_orders.view` only |
