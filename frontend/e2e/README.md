# End-to-end tests

Playwright specs that drive the real stack: Postgres, the FastAPI backend, and a **production**
Next.js build. They are not run by `npx jest` — `jest.config.ts` excludes this directory.

## Running them

```bash
# 1. Database: migrations + seed data (wipes the volume)
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
| `ticket-21-auth.spec.ts` | 1 — authentication, incl. keyboard-only |
| `ticket-21-receiving.spec.ts` | 2 — receiving a delivery → inventory |
| `ticket-21-work-orders.spec.ts` | 3 — work-order lifecycle |
| `ticket-21-inventory.spec.ts` | 4 — traceability & adjustment |
| `ticket-21-locale.spec.ts` | 5 — language toggle & date locale (LR-007) |
| `ticket-21-mobile.spec.ts` | 6 — iPhone 14 viewport (NFR-010) |
| `ticket-19.spec.ts` | User management & audit (ACR-19) |

Two projects are configured: `chromium` runs everything at desktop size, and `mobile` runs only
`ticket-21-mobile.spec.ts` at iPhone 14 dimensions. Select one with `--project=mobile`.

## Writing more of them

A few things this suite learned the hard way:

- **Never hard-code a quantity.** The database is not reset between runs and these flows move
  stock, so read the value from the API first and assert relative to it.
- **`GET /inventory` has no `ORDER BY`.** Page 1 is not a stable window onto the data — two calls
  can return different rows. Use `allLots()` from `helpers/inventory.ts` rather than assuming a lot
  is on the first page.
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
