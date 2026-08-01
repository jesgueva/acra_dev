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
│   ├── scripts/             # seed_fake_data.py (deterministic local data, --scale N)
│   └── tests/               # pytest: unit (mocked) + integration/ + schema (live DB)
├── frontend/
│   ├── app/[locale]/        # operator-facing route surfaces (dashboard, inventory, receiving, …)
│   ├── app/api/auth/        # Next.js server proxies aligning cookies with the backend
│   ├── src/components/      # feature + layout components (shadcn/ui design system)
│   └── messages/            # next-intl catalogs → C-10 i18n
├── scripts/                 # reset-db-and-seed.sh, smoke-test.sh
├── docker-compose.yml       # full stack: db → migrate → backend → frontend (+ seed profile)
└── docs/                    # this note + RISK_LOG.md
```

`models/` ↔ the data design, `schemas/` + `routers/` ↔ the API contracts, `services/` ↔ the
computational methods, `alembic/versions/` ↔ the migration design, `frontend/app/[locale]/` ↔ the
operator surfaces.

The `docker-compose.yml` bring-up sequence shown above is expanded into a packaging diagram and a
day-2 runbook (health checks, teardown, running multiple stacks side by side) in
[`docs/RUNBOOK.md`](RUNBOOK.md).

## Phase 2 direction (where the next sprint lands)

The realignment replaces the lot-centric inventory model with an **append-only `StockMovement`
ledger** keyed by `(item, state, location)`, where on-hand is the sum of signed movements and every
operator surface (receiving, production close, shipment) writes movements rather than mutating rows.
The Sprint I baseline includes **skeleton stubs** for this module (model/service/router raising
`NotImplementedError`) and a placeholder migration, so the structure is in place and aligned with
the design before behavior is implemented. See [`RISK_LOG.md`](RISK_LOG.md) RSK-01/RSK-02 for the
load-bearing risks (concurrency-safe close; reversible migration).

**`state` is the material axis** — `RAW_MATERIAL | WORK_IN_PROGRESS | FINISHED_GOOD`, nullable for
auxiliary items. It is not a lifecycle axis: shipping and consumption are negative movements, not
destination states, and material on the line is WIP plus an active reservation. Lifecycle is
carried by `MovementType` and `StockReservation` for the future ledger, and by
`app.models.inventory.LotStatus` for the lot-centric model in place today.

The authoritative build target — table shapes, the delete/add/migrate list from the ACR-25 decision
gate, and which ticket owns each piece — is `acra_docs/reference/target_schema.md` (ACR-26).
Alembic revisions `010` (stock reservations), `011` (production worksheets), `012` (delivery
notes), `013` (shipping privileges) and `014` (shipment invoices) are taken; the next available
revision is **`015`**.

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

#### Measured against the alternatives (A8-5, ACR-44)

Step 1 rejected SERIALIZABLE on the assertion that it "needs a retry loop to be usable at all".
`scripts/validation/concurrency_bench.py` turns that into a number. One workload — N concurrent
closers drawing stock from one product — with only the concurrency control varied; 5 rounds per
cell, `--stock 1000000 --draw 1000`, PostgreSQL 15.18:

| arm | lost updates | success @32 | goodput @2 → @32 (closes/s) |
|---|---|---|---|
| unguarded read-modify-write | **281 across the sweep** | 3% | 128 → **10** |
| **ADR-02 optimistic + row locks** | **0** | **100%** | 95 → **227** |
| SERIALIZABLE, no retry | 0 | 3% | 156 → 52 |
| SERIALIZABLE + 5 bounded retries | 0 | 21% | 237 → 77 |

Three findings:

1. **ADR-02's protocol is the only arm that scales.** It is alone in holding 100% success and zero
   lost updates at every level from 2 to 32, and alone in *gaining* goodput as concurrency rises
   (95 → 227 closes/s). Every other arm's goodput collapses.
2. **A bounded retry loop does not rescue SERIALIZABLE.** Five retries hold 100% only to 4 closers;
   by 32 the arm still drops 79% of its work. "Needs a retry loop" understates it — it needs an
   *unbounded* one, and that is a queue, not a retry.
3. **Raw throughput inverts the result, which is why the study reports goodput.** Bare SERIALIZABLE
   posts the highest attempts/second in the entire sweep (1648/s at 32) while completing 3% of the
   work, because an abort is nearly free. An evidence table quoting attempts/second would recommend
   the arm that does almost nothing.

The correctness oracle checks the books in **both** directions — stock left over beyond what the
successes claim (a lost update) and stock missing beyond it (over-consumption: an attempt that
decremented and then failed, or drew twice). Only the first appeared in this sweep, but an oracle
that tested one direction would have reported the other as a clean ledger.

The unguarded row is not hypothetical: `inventory_service.adjust_quantity` and
`shipment_service.create_shipment` still carry that shape today (ISS-06).

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

**Also settled here:** the close writes Issue-at-actual per line and nothing else — the
`actual − planned` delta is computed from the worksheet line, never written as an adjustment
movement (`client_domain_model.md` §7.1). The unit suite asserts this on movement *kind and count*,
because a compensating pair of rows nets to the right total while still being wrong. A lot drawn to
zero is moved to `LotStatus.CONSUMED`, mirroring the terminal transition `shipment_service` already
makes; partially drawn lots stay `IN_STORAGE`.

## Verified version snapshot

These are the **declared** versions, not merely the ones the baseline happened to be tested on.
Python comes from `backend/pyproject.toml` (`requires-python`) and Node from `.nvmrc`;
`backend/tests/test_packaging.py` fails the build if this table, the README, or CI drifts from
them (ACR-42 / A10-4).

| Component | Version |
|---|---|
| Python | 3.13 |
| Node.js / npm | 24 / 11 |
| PostgreSQL | 15 |
| FastAPI / SQLAlchemy / Alembic | 0.115 / 2.0 / 1.14 |
| Next.js / React | 16 / 19 |
| Docker / Compose | 29 / v5 |

Backend dependencies: `backend/requirements.txt` holds the **direct** dependencies, every one
exactly pinned; `backend/requirements.lock` holds the full resolved transitive closure and is what
CI and the container images install from. Frontend: `frontend/package-lock.json`.

> Until ACR-42, `google-genai` and `anthropic` were the two lines in `requirements.txt` carrying a
> `>=` range rather than a pin — and two developer virtualenvs built from that same file were
> measured running `anthropic` **0.119.0** and **0.109.2**. Same spec, different code.

## Measurement points (A8-7)

`scripts/validation-run.sh` is a 6-stage evidence harness (stage 6a–6f below); this section marks
where each stage actually sits in the system decomposition above, so a number in the A8 writeup can
be traced back to the boundary it was taken at without reading the shell script.

Same shape as the [system decomposition](#system-decomposition) diagram above, with each edge
tagged by the stage(s) measured there:

```
┌──────────────┐   REST/JSON over HTTP   ┌─────────────────────────┐   SQLAlchemy async   ┌──────────────┐
│ Next.js 16   │ ──────────[6a]─────────▶ │ FastAPI backend          │ ────────[6a,6f]─────▶ │ PostgreSQL 15│
│ App Router   │                         │ router → service → repo  │                       │              │
│ SSR + i18n   │ ◀────────────────────── │ observability.py [6c]     │ ◀─────────────────── │              │
└──────────────┘                         │ (every route, C-01..C-09)│                       └──────────────┘
                                          └───────────┬─────────────┘
                                                     │ image + extraction schema
                                                    [6b,6e]
                                                     ▼
                                            ┌──────────────────────┐
                                            │ Hosted vision-LLM     │  (Gemini ↔ Claude fallback)
                                            │ receiving-doc OCR     │
                                            └──────────────────────┘
```

Stock-drawdown boundary — C-04/C-05, all three concurrency-control shapes, measured together as
**[6d]**: `inventory_service.adjust_quantity` · `shipment_service.create_shipment` ·
`allocation_service.allocate_materials` · worksheet close (ADR-02, above).

| Stage | Script | Component(s) crossed | What it measures | Ticket |
|---|---|---|---|---|
| **6a** | `scripts/validation/pipeline_trace.py` | C-03 → C-04 → C-09, real HTTP against a live backend | Data-pipeline integrity: a receiving document lands correctly in inventory and the audit trail | — (pre-A8 harness) |
| **6b** | `scripts/validation/ocr_roundtrip.py` | C-03, vision-LLM boundary | Real OCR round-trip vs. the recorded accuracy baseline (skipped without an API key) | A8-4 (ACR-36) |
| **6c** | `scripts/validation/api_latency_bench.py` | Router layer, all routes, via `app/core/observability.py` + `app/core/benchmark.py` | p50/p95/p99 request latency, 5 endpoints × 100 requests | A8-2/A8-3 (ACR-43) |
| **6d** | `scripts/validation/concurrency_bench.py` | C-04/C-05 boundary — the 4 stock-drawdown implementations named above | Correctness (lost updates, over-consumption) and goodput at 2→32 concurrent closers | A8-5 (ACR-44) |
| **6e** | `python -m scripts.ocr_bench.run_bench` | C-03, vision-LLM boundary | Gemini vs. Claude head-to-head accuracy/latency over the 7-layout labelled corpus | A8-4 (ACR-36) |
| **6f** | `scripts/validation/aggregation_bench.py` | C-04, `inventory_lots` / migration `015` | Indexed vs. unindexed aggregate-read cost at volume (1k→200k lots) | A8-6 (ACR-45) |

`app/core/benchmark.py` (shared percentiles, provenance) and `app/core/observability.py`
(per-request structured logging) are the two cross-cutting modules every stage above either calls
directly (6c, 6d, 6f) or runs underneath (6a, 6b, 6e all execute inside a running backend that
`observability.py` is instrumenting regardless). Neither appears as its own row in the
[component map](#component-map--repository) — both live under the `core/` cross-cutting bullet in
[Repository tree → design](#repository-tree--design) — which is why they're called out here rather
than assigned a `C-NN` of their own.
