# Architecture Notes

How the ACRA MES codebase is organized, how its layers fit together, and how the repository maps
onto the system design. This is the in-repo orientation note; the full design package (C4
diagrams, ER model, ADRs, API contracts, test/evaluation plan) is maintained in the project's
engineering documentation.

## System decomposition

ACRA MES is a **modular monolith**: a Next.js frontend, a layered FastAPI backend, and a
PostgreSQL database, with receiving-document extraction delegated to a hosted vision-LLM behind a
thin extraction service. This shape fits a single-facility deployment — it keeps one transactional
database and one deploy unit while still separating concerns by module.

```
┌──────────────┐   REST/JSON over HTTP   ┌─────────────────────────┐   SQLAlchemy async   ┌──────────────┐
│ Next.js 16   │ ──────────────────────▶ │ FastAPI backend          │ ───────────────────▶ │ PostgreSQL 15│
│ App Router   │                         │ router → service → repo  │                      │              │
│ SSR + i18n   │ ◀────────────────────── │ JWT · RBAC · audit       │ ◀─────────────────── │              │
└──────────────┘                         └───────────┬─────────────┘                      └──────────────┘
                                                     │ image + extraction schema
                                                     ▼
                                            ┌──────────────────────┐
                                            │ Hosted vision-LLM     │  (Gemini → Claude fallback)
                                            │ receiving-doc OCR     │
                                            └──────────────────────┘
```

## Backend layering

Strict one-way layering — each layer only calls the one below it:

```
HTTP  →  Router      (request validation, status codes, RBAC dependency)
      →  Service     (business rules, transactions, audit writes)
      →  Repository  (SQLAlchemy queries)
      →  PostgreSQL
```

Routers are thin HTTP adapters; **no router touches the database directly** — all business logic
lives in services. Cross-cutting concerns (`core/`) — config, async DB session, security
(JWT/bcrypt), RBAC privilege-union middleware, and the append-only audit helper — are shared by
every module.

## Component map → repository

The design defines ten components (`C-01…C-10`). Here is where each lives in the tree:

| ID | Component | Primary code locations |
|---|---|---|
| C-01 | Auth & RBAC | `backend/app/core/security.py`, `core/rbac.py`, `app/routers/auth.py`, `app/services/auth.py` |
| C-02 | Masters (partners/items/BoM) | `app/routers/contacts.py`, `products.py` + matching `services/` and `models/` |
| C-03 | Receiving + AI extraction | `app/routers/deliveries.py`, `services/delivery_service.py`, `services/ocr_service.py` |
| C-04 | Stock Ledger | **today:** `app/routers/inventory.py`, `services/inventory_service.py`, `models/inventory.py` · **Phase 2:** `models/stock_movement.py`, `services/stock_movement_service.py`, `routers/stock_movements.py` (skeleton) |
| C-05 | Work Order | `app/routers/work_orders.py`, `services/work_order_service.py`, `services/allocation_service.py` |
| C-06 | Production Worksheet | *Phase 2* — builds on the ledger and work-order modules (concurrency-critical close) |
| C-07 | Forklift Worksheet | *Phase 2* — derived from production worksheets |
| C-08 | Shipment | `app/routers/shipments.py`, `services/shipment_service.py`, `models/shipment.py` |
| C-09 | Audit | `app/core/audit.py`, `app/routers/audit.py`, `services/audit_service.py`, `models/audit.py` |
| C-10 | i18n (EN/ES) | `frontend/messages/en.json`, `es.json`, `frontend/src/i18n/` |

C-04 (ledger) and C-09 (audit) are **cross-cutting**: every mutating module routes writes through
them. C-01 guards every route.

## Repository tree → design

```
acra_dev/
├── backend/
│   ├── app/
│   │   ├── main.py          # app assembly + router registration + /health
│   │   ├── core/            # cross-cutting: config, database, security, rbac, audit
│   │   ├── models/          # SQLAlchemy ORM — the data design
│   │   ├── schemas/         # Pydantic request/response contracts (API surface)
│   │   ├── routers/         # HTTP adapters (one per component surface)
│   │   └── services/        # business logic + transactions
│   ├── alembic/versions/    # migrations — schema evolution (001→008, + Phase 2 stub)
│   ├── scripts/             # create_admin.py, seed_fake_data.py (deterministic local data)
│   └── tests/               # pytest: unit (mocked) + integration/ + schema (live DB)
├── frontend/
│   ├── app/[locale]/        # operator-facing route surfaces (dashboard, inventory, receiving, …)
│   ├── app/api/auth/        # Next.js server proxies aligning cookies with the backend
│   ├── src/components/      # feature + layout components (shadcn/ui design system)
│   └── messages/            # next-intl catalogs → C-10 i18n
├── scripts/                 # reset-db-and-seed.sh, smoke-test.sh
├── docker-compose.yml       # PostgreSQL 15 (host 5433) — the DB container
└── docs/                    # this note + RISK_LOG.md
```

`models/` ↔ the data design, `schemas/` + `routers/` ↔ the API contracts, `services/` ↔ the
computational methods, `alembic/versions/` ↔ the migration design, `frontend/app/[locale]/` ↔ the
operator surfaces.

## Phase 2 direction (where the next sprint lands)

The realignment replaces the lot-centric inventory model with an **append-only `StockMovement`
ledger** keyed by `(item, state)`, where on-hand is the sum of signed movements and every operator
surface (receiving, production close, shipment) writes movements rather than mutating rows. The
Sprint I baseline includes **skeleton stubs** for this module (model/service/router raising
`NotImplementedError`) and a placeholder migration, so the structure is in place and aligned with
the design before behavior is implemented. See [`RISK_LOG.md`](RISK_LOG.md) RSK-01/RSK-02 for the
load-bearing risks (concurrency-safe close; reversible migration).

### ADR-02 — worksheet-close concurrency (decided, ACR-30)

**Context.** RSK-01: a production-worksheet close has a lost-update path when several closes race
on the same worksheet or on the same stock. It had to be de-risked before ACR-31 builds the real
close.

**Decision.** The close runs at **Read Committed** (the Postgres default) and executes, in order:

1. `SELECT … FOR UPDATE` on the parent worksheet row — this also fixes the lock order for step 3,
   so two closes cannot deadlock against each other.
2. **One conditional UPDATE** claims the worksheet:
   `SET status='closed', version=version+1 WHERE id=:id AND version=:expected AND status<>'closed'`.
   `rowcount != 1` → **409**. The winner of a race is decided atomically by the database, never by
   a read-then-check — and this happens *before* any stock is touched.
3. `SELECT … FOR UPDATE … ORDER BY id ASC` on the candidate lots — the same order for every caller.
4. Availability check, then a FIFO draw in integer arithmetic, one `consume` transaction per lot.

**SERIALIZABLE was rejected.** `allocation_service.py:22` sets it, but under N-way parallelism it
raises `could not serialize access due to concurrent update`, which reaches the operator as a
**500** rather than a 409 they can act on, and it needs a retry loop to be usable at all.

**Evidence.** `backend/tests/integration/test_worksheet_close_concurrency.py` (TC-02) runs against
real Postgres with each closer on its own connection — a mocked session cannot exhibit a lost
update. 8 closers × 5 rounds by default; also verified at 16 × 20. Exactly one winner every run;
competing worksheets never oversell and never drive on-hand negative; opposing-order multi-lot
closes do not deadlock. A **negative control** implements the unguarded read-modify-write close and
asserts that it *does* lose updates (10000 − 3000 − 3000 → 7000, not 4000). If that control ever
passes, the suite has gone blind and every other assertion in it is worthless.

**Carry-forward for ACR-31 — the one place this does not transfer.** `FOR UPDATE` over **zero rows
locks nothing**. That is benign against `inventory_lots` (no lots ⇒ no stock ⇒ 409 regardless), but
it will **not** be benign for the append-only ledger, where on-hand is an aggregate over
`(item, state)` and a fresh key legitimately has no rows to lock — two closes could then both read
"nothing reserved" and both proceed. The ledger close will need `pg_advisory_xact_lock(hashtext(…))`
on the `(item, state)` key, or a per-`(item, state)` balance anchor row to lock instead.

**Also settled here:** the close writes Issue-at-actual per line and nothing else — the
`actual − planned` delta is computed from the worksheet line, never written as an adjustment
movement (`client_domain_model.md` §7.1). TC-02 asserts this on movement *kind and count*, because
a compensating pair of rows nets to the right total while still being wrong.

## Verified version snapshot

Pinned/verified for the `v0.2.0-sprint1-baseline` tag (see `submissions` evidence in the docs
archive). Nearby versions are expected to work; these are what the baseline was smoke-tested on.

| Component | Version |
|---|---|
| Python | 3.13 |
| Node.js / npm | 24 / 11 |
| PostgreSQL | 15 |
| FastAPI / SQLAlchemy / Alembic | 0.115 / 2.0 / 1.14 |
| Next.js / React | 16 / 19 |
| Docker / Compose | 29 / v5 |

Backend dependencies are pinned in `backend/requirements.txt`; frontend in
`frontend/package-lock.json`.
