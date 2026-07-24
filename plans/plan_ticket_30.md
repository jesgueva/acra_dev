# Plan — ACR-30: Concurrency-safe worksheet-close spike (zero lost update)

**Ticket:** [ACR-30](https://linear.app/chronos-laboral/issue/ACR-30/concurrency-safe-worksheet-close-spike-zero-lost-update) · Urgent · Backlog
**Branch:** `ticket-30/concurrency-safe-worksheet-close-spike` off `origin/master` (`9f72293`)
**Blockers:** ACR-23 (Inventory Ledger redesign) — **Done** ✅
**Refs:** `docs/RISK_LOG.md` RSK-01 · ADR-02 · TC-02 · SC-4
**Scope:** backend-only spike + one e2e assertion. No new frontend surface.

---

## 1. Current state

### The guarantee has nothing to stand on yet

The ledger this ticket nominally protects **does not exist as a table on `master`**:

- `backend/app/models/stock_movement.py:1` — module docstring says *"Deliberately **not** mapped to
  a table or registered with Alembic yet."* It exports only two enums, `StockState` and
  `MovementType`.
- `backend/app/services/stock_movement_service.py:19` — `record_movement()` and `on_hand()` both
  `raise NotImplementedError`.
- `backend/app/routers/stock_movements.py:20` — every route returns **501**.
- `backend/alembic/versions/009_stock_movement_ledger_placeholder.py:20` — `upgrade()` is `pass`.

The **live** inventory model is still lot-centric:

- `backend/app/models/inventory.py:5` — `InventoryLot(quantity_on_hand INT, status, product_id, …)`
  with `CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_lots_qty")` at
  `inventory.py:26`. Quantities are integers ×100.
- `backend/app/models/inventory.py:31` — `InventoryTransaction(lot_id, transaction_type, quantity, …)`,
  whose check constraint already permits `'consume'` and `'produce'` (`inventory.py:45`).

There is no `production_worksheets` table anywhere on `master`.

### The closest existing pattern to imitate

`backend/app/services/allocation_service.py:21` — FIFO allocation, and the only place in the
codebase that takes locks:

```python
await db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))   # :22
select(WorkOrder).where(WorkOrder.id == wo_id).with_for_update()          # :25
… .order_by(Product.name, InventoryLot.id.asc()).with_for_update()        # :61
```

It locks the parent row, then the lots in a deterministic order — exactly the shape ACR-30 needs.
Two things it does **not** do, which is precisely the RSK-01 gap: no optimistic version guard (so a
double-submit of the same allocation is only prevented by the `status != 'created'` read, which is
not atomic), and no test that ever proves the locking works.

### The existing "concurrency test" proves nothing

`backend/tests/integration/test_concurrency.py:60` builds a **fresh `AsyncMock` session per
request**. It fires 20 concurrent `GET /inventory` and asserts they all return 200. There is no
database, no transaction, no write — it cannot detect a lost update by construction. TC-02 needs a
genuinely different harness.

### Infrastructure that already supports a real-DB test

- `.github/workflows/ci.yml:12` — CI runs a **`postgres:15` service**, applies `alembic upgrade head`,
  then `pytest … --cov-fail-under=85`. A live-DB test will run in CI.
- `backend/tests/test_schema.py:11` — precedent for live-DB tests: connects with `asyncpg` straight
  off `DATABASE_URL`, no skip guard.
- `backend/pytest.ini` — `asyncio_mode = auto`, so `async def test_…` needs no decorator.
- `backend/tests/conftest.py:26` — `_make_session` / `_make_user` / `_override`, the mocked-RBAC
  3-query helpers, for the unit layer.

### Migration chain

Head on `master` is `009`. `docs/architecture.md` states *"The next available Alembic revision is
`010`."* **In-flight collision:** the ACR-27 worktree holds an uncommitted
`010_stock_reservations.py` (also `down_revision = "009"`). See §6.

---

## 2. The one real design decision

> **The spike proves the *protocol*, against the schema that actually runs today.**

The close is implemented against **`inventory_lots` + `inventory_transactions`**, not against a new
`stock_movements` ledger table.

**Why:**

1. **It is testable today.** `inventory_lots.quantity_on_hand` is a real column with a real
   `>= 0` constraint. "Correct on-hand every run" is directly assertable. A ledger table would have
   to be invented first, and then the spike would be proving a guarantee about a schema no other
   code uses.
2. **Zero collision with the two In Progress tickets.** ACR-26 owns the `StockState` vocabulary and
   the target ledger shape; ACR-27 owns reservations. If ACR-30 defines `stock_movements`, it
   pre-empts ACR-26's whole deliverable. The spike therefore touches **neither** `StockState` nor
   reservations — worksheet lines key on `product_id` only.
3. **The protocol transfers unchanged.** Optimistic version guard + deterministic-order row locks +
   affected-rowcount assertion is schema-independent. ACR-31 applies the same three steps to the
   ledger. §7 records the one place it does *not* transfer cleanly.

**Consequences, recorded deliberately:**

- No reservation release on close (ACR-27's table isn't on `master`) → ACR-31.
- No Finished-Good receipt movement on close → ACR-31.
- No `actual − planned` adjustment entries → ACR-31.
- `production_worksheets` is created with **only the columns the close needs**. ACR-29 extends it
  (`work_order_id` explosion, `status='reserved'`, reservation FKs); it does not have to undo it.

---

## 3. Change list

### CREATE

| File | Purpose |
|---|---|
| `backend/alembic/versions/010_production_worksheets.py` | `production_worksheets` + `production_worksheet_lines`; seed 3 privileges. Reversible. |
| `backend/app/models/production_worksheet.py` | `ProductionWorksheet` (carries `version`) + `ProductionWorksheetLine`. |
| `backend/app/schemas/production_worksheet.py` | `WorksheetCreate`, `WorksheetLineCreate`, `WorksheetCloseRequest`, `WorksheetCloseLine`, `WorksheetResponse`, `WorksheetLineResponse`. |
| `backend/app/services/production_worksheet_service.py` | `create_worksheet`, `get_worksheet`, **`close_worksheet`** (the protocol). |
| `backend/app/routers/production_worksheets.py` | 3 routes, RBAC-guarded. |
| `backend/tests/test_production_worksheets.py` | Mocked unit tests — happy path, RBAC 403, validation, 404/409. |
| `backend/tests/integration/test_worksheet_close_concurrency.py` | **TC-02** — live Postgres, N-parallel closes, + negative control. |
| `frontend/e2e/ticket-30.spec.ts` | Close via API → Inventory page shows the decrement. |

### MODIFY

| File | Change |
|---|---|
| `backend/app/models/__init__.py` | Export the two new models (`__init__.py:1-30` pattern). |
| `backend/app/main.py` | Import + `include_router` (`main.py:52-75`). Known merge-conflict point. |
| `docs/RISK_LOG.md` | RSK-01 → **Mitigated**, with the finding and the date. |
| `docs/architecture.md` | Short "ADR-02 — worksheet-close concurrency" subsection under Phase 2 direction. |

---

## 4. Data / API

### Schema (migration `010`)

```
production_worksheets
  id                SERIAL PK
  work_order_id     INT NULL  → work_orders.id      -- nullable; ACR-29 makes it the driver
  production_line   VARCHAR(100) NULL
  scheduled_date    VARCHAR(20) NULL                 -- matches shipments.shipment_date style
  status            VARCHAR(20) NOT NULL DEFAULT 'draft'
  version           INT NOT NULL DEFAULT 0           -- ← the optimistic guard
  created_by        INT NULL → users.id
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
  closed_at         TIMESTAMPTZ NULL
  CHECK status IN ('draft','in_progress','closed')   -- ACR-29 adds 'reserved'
  CHECK version >= 0

production_worksheet_lines
  id                SERIAL PK
  worksheet_id      INT NOT NULL → production_worksheets.id ON DELETE CASCADE
  product_id        INT NOT NULL → products.id
  planned_quantity  INT NOT NULL      -- ×100, > 0
  actual_quantity   INT NULL          -- ×100, >= 0, set at close
  CHECK planned_quantity > 0
  CHECK actual_quantity IS NULL OR actual_quantity >= 0
  INDEX ix_pwl_worksheet (worksheet_id)
```

No `state` column on lines — deliberate (§2). Stock is drawn from
`inventory_lots WHERE status = 'in_storage'`.

`downgrade()` drops both tables and deletes the seeded privilege rows — mirrors ACR-27's
migration-010 shape and satisfies RSK-02 (reversible).

### Privileges (seeded in the migration, `002_role_privilege_assignments.py:38` pattern)

| Privilege | company_admin | production_supervisor |
|---|:--:|:--:|
| `production.worksheet.view` | ✅ | ✅ |
| `production.worksheet.create` | ✅ | ✅ |
| `production.worksheet.close` | ✅ | ✅ |

`machine_operator` and `receiving_clerk` get **none** — that is the 403 the tests assert.

### Endpoints

| Method | Path | Privilege | Notes |
|---|---|---|---|
| `POST` | `/api/v1/production-worksheets` | `production.worksheet.create` | Body `{production_line?, scheduled_date?, work_order_id?, lines:[{product_id, planned_quantity}]}` → **201** + `version: 0`. |
| `GET` | `/api/v1/production-worksheets/{id}` | `production.worksheet.view` | **200** / **404**. |
| `POST` | `/api/v1/production-worksheets/{id}/close` | `production.worksheet.close` | Body `{expected_version:int, lines:[{line_id, actual_quantity}]}` → **200**. |

`close` failure modes — all `409 CONFLICT`, distinguishable by `detail`:

| Cause | Detail |
|---|---|
| `expected_version` ≠ current | `Worksheet was modified by another operation (expected version N).` |
| already `closed` | `Worksheet is already closed.` |
| on-hand < actual for a line | `Insufficient stock for product <id>. Required: X, available: Y.` |

`404` unknown worksheet · `422` malformed body (negative `actual_quantity`, unknown `line_id`,
empty `lines`).

### The protocol — `close_worksheet()`

Ordered exactly like this; the order *is* the deliverable.

1. **Read Committed** (Postgres default — do **not** copy `allocation_service.py:22`'s
   `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`). Rationale in §7.
2. Lock the parent: `select(ProductionWorksheet).where(id == …).with_for_update()`.
   404 if missing. This also fixes the lock order for step 4, so two closes can never deadlock.
3. **Optimistic guard as an atomic UPDATE**, before any stock is touched:
   ```sql
   UPDATE production_worksheets
      SET status = 'closed', version = version + 1, closed_at = now()
    WHERE id = :id AND version = :expected AND status <> 'closed'
   ```
   `result.rowcount != 1` → **409**. The winner of a concurrent race is decided here, atomically,
   by the database — not by a read-then-check.
4. Lock the stock: for the union of `product_id`s on the closing lines,
   ```python
   select(InventoryLot)
     .where(InventoryLot.product_id.in_(pids),
            InventoryLot.status == "in_storage",
            InventoryLot.quantity_on_hand > 0)
     .order_by(InventoryLot.id.asc())
     .with_for_update()
   ```
   Ascending-`id` order across every caller ⇒ no lock-ordering deadlock.
5. Per line: sum locked on-hand; `< actual_quantity` → **409** (rolls back the step-3 update too,
   so the worksheet stays open and retryable). Otherwise draw FIFO across lots, decrementing with
   **integer** arithmetic (`allocation_service.py:88` casts to `float` — a pre-existing wart this
   spike does not copy), and write one `InventoryTransaction(transaction_type='consume',
   quantity=-taken, reference_type='production_worksheet', reference_id=worksheet_id)` per lot
   touched.
6. `write_audit(action="production_worksheet_closed", …)` — `app/core/audit.py:7`, caller commits.
7. Single `await db.commit()`.

---

## 5. Test plan

### 5a. Unit — `backend/tests/test_production_worksheets.py` (mocked, conftest helpers)

Imports `_make_session`, `_make_user`, `_override` from `tests/conftest.py`. RBAC burns
execute calls 0–2; service queries start at index 3.

| # | Case | Expect |
|---|---|---|
| 1 | create, valid body, `production.worksheet.create` | 201, `version == 0`, lines echoed |
| 2 | create as `machine_operator` (no privilege) | **403** |
| 3 | create with `lines: []` | 422 |
| 4 | create with `planned_quantity: 0` / negative | 422 |
| 5 | get, exists | 200 |
| 6 | get, missing | 404 |
| 7 | get without `production.worksheet.view` | **403** |
| 8 | close, happy path | 200, status `closed`, `version == 1` |
| 9 | close without `production.worksheet.close` | **403** |
| 10 | close, stale `expected_version` (rowcount 0) | 409 + "modified by another operation" |
| 11 | close, already closed | 409 |
| 12 | close, insufficient stock | 409 + "Insufficient stock" |
| 13 | close, `actual_quantity: -5` | 422 |
| 14 | close, `line_id` not on this worksheet | 422 |
| 15 | close, unknown worksheet id | 404 |

Coverage gate — must clear 85% on each:
```bash
pytest tests/test_production_worksheets.py \
  --cov=app.routers.production_worksheets \
  --cov=app.services.production_worksheet_service \
  --cov=app.models.production_worksheet \
  --cov=app.schemas.production_worksheet --cov-report=term-missing
```

### 5b. **TC-02** — `backend/tests/integration/test_worksheet_close_concurrency.py` (live Postgres)

Its own `create_async_engine(DATABASE_URL)` + `sessionmaker`; **one session per concurrent closer**,
because sharing a session shares a connection and would serialize the race away. Fixtures create
and tear down their own product / lot / worksheet rows so the test is re-runnable.

| # | Scenario | Assertion |
|---|---|---|
| 1 | **Same worksheet, N=8 parallel closes.** Lot on-hand 10000, one line, actual 6000. | Exactly **1** success, **7** × 409. Final on-hand `== 4000`, never `-2000`×k. Exactly **1** `inventory_transactions` consume row. `version == 1`. |
| 2 | **Repeatability.** Scenario 1 × **5 rounds**, fresh rows each round. | 5/5 identical. Flake ⇒ ticket fails. |
| 3 | **Different worksheets, same stock.** 6 worksheets × actual 2000 against on-hand 10000 (demand 12000 > supply). | `successes == 5`, `failures == 1` with 409 "Insufficient stock". Final on-hand `== 0` and **never negative** — the `ck_inventory_lots_qty` constraint must never be the thing that catches it. |
| 4 | **Multi-line, multi-lot, ordered locking.** 2 worksheets, lines touching products A and B in opposite order, FIFO across 3 lots each. | Both resolve; no deadlock (test wrapped in `asyncio.wait_for(..., 20)`); on-hand exact. |
| 5 | **Negative control.** A read-modify-write close written *inside the test file* — plain `SELECT quantity_on_hand` → compute → `UPDATE`, no lock, no version guard. | **Loses updates**: final on-hand is provably wrong / more than one consume row. Without this, a green suite proves only that the harness is asleep. |

Following `tests/test_schema.py`, these require a live DB and are not skip-guarded — CI provides one.

### 5c. Frontend — `frontend/e2e/ticket-30.spec.ts`

No new UI, so the e2e proves the **stock actually moved where an operator can see it**:

1. `login(admin/admin123)` (helper copied from `e2e/ticket-19.spec.ts:15`).
2. Go to `/en/inventory`, read the on-hand for the seeded product.
3. Via Playwright's `request` context: `POST` create worksheet → `POST` close.
4. Reload `/en/inventory` → on-hand decreased by exactly the closed actual.
5. Second `POST` close with the same `expected_version` → **409**, inventory unchanged after reload.

Run against `npm run build && npm run start` on :3000, **never `next dev`** (KI-02).

### 5d. Full gate

`pytest tests/ --cov=app --cov-fail-under=85` · `npx jest` (subset) · `npm run lint` ·
`npm run build` · `./scripts/smoke-test.sh` · `npx playwright test e2e/ticket-30.spec.ts`

---

## 6. Live verification

```bash
./scripts/reset-db-and-seed.sh          # DATABASE_URL per the real port — see Risks
cd backend && alembic upgrade head && uvicorn app.main:app --port 8000
cd frontend && npm run build && npm run start
```

Walk it:

1. `/en/login` as `admin` / `admin123`; note a product's on-hand on `/en/inventory`.
2. `POST /api/v1/production-worksheets` with one line → 201, `version: 0`.
3. Fire **8 parallel** closes from a shell (`xargs -P8 curl`) → exactly one 200, seven 409.
4. Reload `/en/inventory` → on-hand decremented **once**. Check `/en/audit` for a single
   `production_worksheet_closed` entry.
5. Re-close with the stale version → 409; inventory unchanged.
6. Log in as `operator1` (machine_operator) → close returns **403** (blocked at the API, not merely
   hidden in the UI).
7. Watch the browser console + network panel throughout: no unhandled errors, no 500s. A 500 in
   place of a 409 is a **failure**, not a pass.

---

## 7. Risks / open questions

**Decided — not blocking, recorded here:**

1. **Read Committed, not SERIALIZABLE.** `allocation_service.py:22` uses SERIALIZABLE. Under N-way
   parallelism SERIALIZABLE returns `could not serialize access due to concurrent update`, which
   surfaces as a **500**, not the 409 the operator needs — and it needs a retry loop to be usable.
   Read Committed + `FOR UPDATE` is deterministic: the second closer blocks, then re-reads the
   committed row (Postgres EPQ recheck) and loses the version guard cleanly. If TC-02 shows this
   does not hold, the finding gets documented and SERIALIZABLE-with-retry is the fallback — which
   is exactly the escape hatch the ticket's acceptance criteria allow for.
2. **`FOR UPDATE` over zero rows locks nothing.** Benign *here* — no lots means no stock means 409
   regardless. It will **not** be benign for the append-only ledger, where `on_hand` is an
   aggregate and a fresh `(item, state)` key legitimately has zero rows. **This is the headline
   finding for ACR-31:** the ledger close will need `pg_advisory_xact_lock(hashtext(...))` or a
   per-`(item, state)` balance anchor row. Written into `docs/architecture.md`.
3. **Spike scope excludes** FG receipt, reservation release, and `actual − planned` deltas — all
   ACR-31, all called out in §2.

**Needs a human eye at merge time (not before implementation):**

4. **Migration number collision.** ACR-27's uncommitted `010_stock_reservations.py` also claims
   `down_revision = "009"`. This plan takes `010` because a gap breaks the chain. Whichever PR
   merges **second** renumbers itself to `011` and re-points `down_revision`. Flagged in the PR body.
5. **Table-name overlap with ACR-29.** ACR-29 ("create-from-WO + reserve") will own
   `production_worksheets`. This spike creates it minimally and additively; ACR-29 extends via `011`+
   rather than replacing. If the user would rather the spike use a throwaway table name, say so —
   otherwise the shared table is the intent.
6. **Postgres port.** `CLAUDE.md` documents 5433, but that port is squatted by another project's
   stack and local `backend/.env` points at **5434**. Check the port before starting; export
   `DATABASE_URL` to match reality, not the docs.
7. **`quantity_on_hand` is `Integer` (×100) but `allocation_service.py:88` assigns `float` to it.**
   Pre-existing; this spike uses integer arithmetic throughout and does not attempt the fix.

---

## 8. Build order

1. `010` migration + models + `models/__init__.py` export → `alembic upgrade head` and confirm the
   two tables and three privilege rows exist.
2. Pydantic schemas.
3. `create_worksheet` / `get_worksheet` + router + `main.py` wiring → **unit tests 1–7 green**.
4. `close_worksheet` with the full protocol → **unit tests 8–15 green**.
5. **TC-02** live-DB concurrency test, negative control (#5) **written first** so the harness is
   proven able to detect a lost update before the safe path is asserted.
6. `frontend/e2e/ticket-30.spec.ts` against a production build.
7. Live browser + parallel-curl walkthrough (§6), screenshots.
8. `docs/RISK_LOG.md` RSK-01 → Mitigated; ADR-02 note in `docs/architecture.md` carrying the §7.2
   finding forward to ACR-31.
9. Full gate (§5d), then draft PR — body ends `Closes ACR-30`, with the §7.4 migration-renumber
   warning.

---

## 9. Addendum — verified against `acra_docs` (2026-07-23)

Two constraints from the domain docs that the plan above satisfies but did not cite. Recorded so
neither is lost at implementation time.

### 9.1 The `actual − planned` delta must never become a movement — and ACR-30 is named

`acra_docs/reference/client_domain_model.md` §7.1 is **binding on this ticket by name**:

> *"Binding on **ACR-31** (close-with-consumption) and **ACR-30** (concurrency spike) — the spike
> proves concurrent correctness, not arithmetic correctness, and would have certified a close that
> double-counts by design."*

The Issue is already written at `actual_quantity`, so an additional adjustment row for the delta
corrects something that was never wrong — over-consumption invents phantom loss, under-consumption
invents phantom stock a later worksheet will reserve and the forklift operator will not find. The
failure is **silent**.

§2 of this plan already excludes delta entries. The addition: **TC-02 asserts it.** Every
concurrency scenario in §5b checks the `inventory_transactions` rows by **kind and count**, not only
by the resulting on-hand total — a close that produced the right number via a compensating pair of
rows must fail the test. Concretely, scenario 1 asserts exactly one `consume` row **and zero
`adjust` rows** for the worksheet's `reference_id`.

### 9.2 The `StockState` vocabulary is mid-flight — this plan is immune by construction

`acra_docs/reference/target_schema.md` §2 replaces the lifecycle axis on `master`
(`in_storage / in_production / shipped / consumed`, `backend/app/models/stock_movement.py:16`) with a
**material** axis (`RAW_MATERIAL | WORK_IN_PROGRESS | FINISHED_GOOD`) under ACR-26, which is In
Progress on another branch.

§7 of that same document records ACR-27 being caught by exactly this: it baked the superseded
vocabulary into a live CHECK constraint in its uncommitted migration `010`, and
`reservation_service.py:116` references `StockState.IN_STORAGE`, a member that no longer exists —
"both branches are green in isolation; merging them raises `AttributeError`."

**ACR-30 cannot be caught the same way:** §2's decision keys worksheet lines on `product_id` alone
and the plan imports neither `StockState` nor `MovementType`. The only vocabulary this branch touches
is `inventory_lots.status == 'in_storage'`, which is pre-existing production code that ACR-26 owns
migrating. **Do not add a `state` column to `production_worksheet_lines` "for ACR-29's benefit"** —
that is precisely how ACR-27 acquired the conflict. ACR-29 adds it, in the vocabulary that wins.
