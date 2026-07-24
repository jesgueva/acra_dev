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

### ADR-02 — worksheet-close concurrency (spiked in ACR-30)

RSK-01 was de-risked ahead of the real close. The protocol `close_worksheet` proves out, in order:

1. **Read Committed** — *not* the `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE` that
   `allocation_service.allocate_materials` uses. Under N-way parallelism SERIALIZABLE aborts the
   losers with `could not serialize access`, which reaches the operator as a 500 and needs a retry
   loop to be usable at all. Row locks give the loser a deterministic 409 instead.
2. **Lock the parent row** (`SELECT ... FOR UPDATE`), which also fixes the lock order for step 4.
3. **Optimistic version guard as one atomic statement** —
   `UPDATE ... WHERE id = :id AND version = :expected AND status <> 'closed'`, judged by rowcount.
   Not a read-then-check: PostgreSQL re-evaluates the predicate against the freshly committed row,
   so the winner of a race is chosen by the database. This step alone is sufficient against a
   double-close; step 2 only makes the failure deterministic.
4. **Lock every affected stock row in ascending id order** — one global order across all callers,
   so concurrent closes queue instead of deadlocking.

Verified by TC-02 (`backend/tests/integration/test_worksheet_close_concurrency.py`) against live
PostgreSQL: 8 parallel closes × 5 rounds, one winner and correct on-hand every run. The suite is
mutation-verified — deleting the version guard turns two tests red, deleting the row locks turns
the oversell test red — so it cannot pass by accident.

**Carried forward to ACR-31.** Two findings do not transfer for free when the close moves onto the
append-only ledger:

- **`FOR UPDATE` over zero rows locks nothing.** Harmless against `inventory_lots` (no lots means
  no stock means a 409 regardless), but on a ledger where on-hand is an aggregate, a fresh
  `(item, state)` key legitimately has zero rows and two closers would serialize against nothing.
  The ledger close needs `pg_advisory_xact_lock(hashtext(...))` or a per-`(item, state)` balance
  anchor row.
- **Rolling back expires ORM instances.** Reading an attribute off one afterwards triggers
  synchronous IO and raises `MissingGreenlet` on an async session, turning a clean 409 into a 500.
  Capture anything an error message needs *before* `await db.rollback()`.

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
