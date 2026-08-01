# Plan — ACR-45 · A8-6 Aggregation benchmark at volume (RSK-04)

**Status:** draft for review
**Written against:** `origin/master` @ `0547b38` (`ticket-44: A8-5 — comparative concurrency study (#38)`)
**Date:** 2026-07-31
**Branch:** `ticket-45/aggregation-benchmark`
**Ticket:** [ACR-45](https://linear.app/chronos-laboral/issue/ACR-45/a8-6-aggregation-benchmark-at-volume-rsk-04) · plan item A8-6 of `plans/plan_a8_a10_readiness.md`

Backend-only. No UI, no new endpoint, no new privilege.

---

## 1. Current state

### 1.1 The four aggregation paths under test

| Path | Shape | `file:line` |
|---|---|---|
| `reservation_service.availability` | composes two independent aggregates per call | `backend/app/services/reservation_service.py:112` |
| ↳ `_on_hand` | `SUM(inventory_lots.quantity_on_hand) WHERE product_id = ? AND status = ?` | `reservation_service.py:43` |
| ↳ `_reserved` | `SUM(stock_reservations.quantity) WHERE product_id = ? AND state = ? AND status = 'active'` | `reservation_service.py:59` |
| `inventory_service.list_alerts` | `SUM(quantity_on_hand) GROUP BY product_id` over **all** lots, no `WHERE` | `backend/app/services/inventory_service.py:339-342` |
| `inventory_service.list_inventory` | `COUNT(*)` over a subquery + a `LIMIT/OFFSET` page + 2 lookup queries | `inventory_service.py:70-105` |
| `inventory_service.export_csv` | the same base query **unpaginated** — every lot into memory | `inventory_service.py:418-451` |

All four are reachable behind `require_privilege("inventory.view")` (`backend/app/routers/inventory.py:36,52,71,84`).

### 1.2 The standing hypothesis — confirmed statically, still needs EXPLAIN

RSK-04's own mitigation (*"index by `(item, state)`"*) is **half-applied**:

- `StockReservation.__table_args__` carries `Index("ix_stock_reservations_item_state", "product_id", "state", "status")` — `backend/app/models/reservation.py:50`, created in `backend/alembic/versions/010_stock_reservations.py:53`.
- `InventoryLot.__table_args__` is **two `CheckConstraint`s and nothing else** — `backend/app/models/inventory.py:57-64`. `product_id` is a bare FK column with no `index=True` (`inventory.py:46`); `status` is a bare `String(20)` (`inventory.py:49`). No `create_index` for `inventory_lots` exists in any of the 14 revisions.

So on every `availability()` call the `_reserved` half is indexed and the `_on_hand` half is not. If RSK-04 is real, that asymmetry is where it lives. **This is a hypothesis about the query planner, and only `EXPLAIN (ANALYZE, BUFFERS)` settles it** — a seq scan on a small table is the correct plan, so "no index" is not by itself a defect.

### 1.3 What the existing RSK-04 evidence actually proves

`backend/tests/integration/test_reservation_availability.py:308-361` (`test_availability_latency_budget`) is the only measurement that exists. It is thin in four specific ways, and naming them is what A8-6 has to fix:

1. **200 lots, one product** (`:43`) — far below any volume where a seq scan hurts.
2. **20 samples** (`:41`) — a p95 over 20 samples is the 19th value; it is not a p95.
3. **200 ms budget** (`:40`) — loose enough that a genuine regression passes.
4. It measures **only** `availability`. `list_alerts`' unbounded `GROUP BY` and `export_csv`'s unbounded fetch are unmeasured, and they are the two paths with no pagination ceiling at all.

It is not wrong, and it already uses the shared `percentiles()` (`:24`, `:345`). A8-6 extends this evidence rather than replacing it.

### 1.4 Infrastructure already on master — reuse, do not rebuild

- **`backend/app/core/benchmark.py`** (ACR-43) — `percentiles()` nearest-rank, `RunMetadata.capture()` provenance (git SHA/tag/dirty, host, Python, redacted DSN, UTC timestamp, exact command), `BenchmarkRun` → `<name>.json` + `<name>.txt` under `validation-evidence/` (gitignored). `Outcome` defaults to `OK`, so a pure-latency run serialises in the original A8-2 shape.
- **`backend/scripts/seed_fake_data.py`** (ACR-41) — `--scale N`. `DELIVERIES_PER_SCALE = 24` (`:347`); scale N is a strict superset of scale 1.
- **`scripts/validation/api_latency_bench.py`** (A8-2) — the closest pattern for an HTTP-level bench: warm-up discard, per-endpoint `BenchmarkRun`, `argparse` with `OUT_DIR` positional, exit 0 unless the run itself failed.
- **`scripts/validation/concurrency_bench.py`** (A8-5) — the closest pattern for a DB-level bench that seeds its own fixture: `--levels 2,4,8,16,32`, `--rounds`, scratch-DB contract in the docstring, `create_async_engine` + `async_sessionmaker` directly.
- **`scripts/validation-run.sh`** — stages `6a`…`6d` exist (`:92,97,107,114`). **A8-6 is stage `6e`.**

### 1.5 Next Alembic revision

Head is `014` (`backend/alembic/versions/014_shipment_invoices.py:27`). **Next free is `015`.** `010_stock_reservations.py:53,75` is the in-repo pattern for a reversible `create_index` / `drop_index` pair.

> ⚠️ **Merge hazard.** `plan_a8_a10_readiness.md` §2.2 Option A (the ledger) also claims `015`. That decision is still open and A8-6 is landing now, so A8-6 takes `015` and the ledger becomes `016` if it is ever built. Flag this in the PR body.

---

## 2. Methodology — three traps that would invalidate the numbers

These are the reason this ticket is worth doing carefully rather than quickly. Each one produces a *plausible-looking* benchmark that proves nothing.

### Trap 1 — the seed creates zero reservations

`grep -i reservation backend/scripts/seed_fake_data.py` returns **nothing**. `stock_reservations` is empty at every `--scale`.

So benchmarking `availability()` against seeded data compares a seq scan over N lots against an **index scan over an empty table**. That is not the indexed-vs-unindexed asymmetry of §1.2 — it is a comparison against zero rows, and it would make the index look far better than it is.

**Therefore:** the bench seeds its own `StockReservation` rows in proportion to the lots it is measuring against, in the same `(product_id, state)` distribution, with a realistic active/released mix. `test_reservation_availability.py:317-333` is the shape to lift (it seeds 200 reservations, half released).

### Trap 2 — stale planner statistics

Postgres chooses plans from `pg_statistic`, not from row counts. After a bulk seed, and again immediately after `CREATE INDEX`, statistics are stale — autovacuum has not caught up. Benchmarking straight through gives a "before" and an "after" that may differ only because the planner re-analyzed, not because the index helped.

**Therefore:** `ANALYZE inventory_lots, stock_reservations` after seeding and after each DDL change, and record in the artifact that it was run. A benchmark that does not say whether it analyzed is not repeatable.

### Trap 3 — measuring the wrong layer

`api_latency_bench.py` measures over HTTP, so every sample carries FastAPI routing, RBAC's three queries (`CLAUDE.md`: `require_privilege` fires exactly 3 DB queries before any service logic), Pydantic serialisation and JSON encoding. At small volume that overhead **dominates** the aggregation being studied, and an index that halves the SQL moves the endpoint number by a few percent.

**Therefore:** measure at the **service layer** — call `reservation_service.availability(db, ...)` directly against a real `AsyncSession`, as `concurrency_bench.py` does. Optionally report the HTTP number alongside for context, clearly labelled as including fixed overhead. The index decision is made on the service-layer number.

---

## 3. Change list

### CREATE

| File | Purpose |
|---|---|
| `scripts/validation/aggregation_bench.py` | The A8-6 sweep. Seeds reservations, runs the 4 paths across `--scale` steps, captures `EXPLAIN (ANALYZE, BUFFERS)` per path, writes one `BenchmarkRun` artifact pair per (path, scale) plus a combined `aggregation-bench-summary.json` carrying the curve. |
| `backend/alembic/versions/015_inventory_lots_aggregation_index.py` | **Conditional on the measurement.** Reversible `create_index` / `drop_index` on `inventory_lots`. Written only if §5's decision gate says the index wins. |
| `backend/tests/integration/test_aggregation_at_volume.py` | Integration gate: correctness of all four paths at volume + a tightened, evidence-derived latency budget. |
| `backend/tests/test_aggregation_bench.py` | Unit tests for the bench's pure helpers (scale planning, EXPLAIN parsing, curve assembly) — no DB. |

### MODIFY

| File | Change |
|---|---|
| `backend/app/models/inventory.py` | Add the `Index(...)` to `InventoryLot.__table_args__` so the ORM and the migration agree (mirrors `models/reservation.py:50`). Conditional on §5. |
| `scripts/validation-run.sh` | Add **stage 6e** — aggregation benchmark — following the `6c`/`6d` block shape. |
| `docs/RISK_LOG.md:22` | RSK-04 → status updated with the measured numbers, dated, and an explicit keep-or-retire call on the periodic-snapshot fallback. |
| `backend/tests/integration/test_reservation_availability.py` | Tighten `LATENCY_BUDGET_MS` / raise `LATENCY_SAMPLES` (`:40-41`) to the evidence-backed values, with a comment citing the artifact. Do **not** duplicate coverage — the new integration file owns the volume cases. |
| `plans/plan_a8_a10_readiness.md` | Flip the A8-6 row in §8.1 and append the §8.2 evidence row. |
| `README.md` | One line for the new validation stage, matching how 6c/6d are described. |

**Explicitly NOT changing:** the four service functions' logic. A8-6 is a *measurement* ticket. If the measurement reveals a query that should be rewritten (e.g. `availability` collapsing its two aggregates into one round trip), that is a **finding to report and ticket**, not scope to absorb here — with one exception, §5.3.

---

## 4. The benchmark design

### 4.1 Sweep

- **Scales:** `--scales 1,10,50,200` (default). At `DELIVERIES_PER_SCALE = 24` and ~3 items/delivery this is roughly 72 / 720 / 3 600 / 14 400 lots. 200 is the point where a seq scan should be unambiguous if it is ever going to be.
- **Samples:** 100 per (path, scale) after 5 warm-up discards — matching `api_latency_bench.py`'s `WARMUP = 5` and default `--requests 100`, so the two tools' numbers are comparable.
- **Arms:** `without-index` then `with-index`, applied as real DDL inside the run, with `ANALYZE` between. Same process, same session pool, same seed → the only variable is the index.
- **Reservations:** seeded at ~1 active + 1 released per lot for the measured products (Trap 1).

### 4.2 Artifacts under `validation-evidence/`

- `aggregation-<path>-scale<N>-<arm>.json` / `.txt` — one `BenchmarkRun` pair each, provenance-stamped.
- `aggregation-bench-summary.json` — the latency curve across scales for every (path, arm), plus row counts, plus whether `ANALYZE` ran.
- `aggregation-explain-<path>-<arm>.txt` — the `EXPLAIN (ANALYZE, BUFFERS)` plans, before and after. **This is the evidence that answers the ticket**, more than the latency numbers: a plan flipping from `Seq Scan` to `Index Scan` is categorical, where a millisecond delta on a laptop is noise.

### 4.3 Exit contract

Exit 0 for a completed sweep even if the index turns out not to help — that is a finding, not a failure. Non-zero only if the sweep could not be carried out (no DB, migrations not applied, seed failed). Same contract `concurrency_bench.py:33-35` uses, for the same reason.

### 4.4 Scratch-database contract

The bench seeds at scale 200 and creates/drops an index. It **must not** run against a database anyone cares about. Docstring carries the `DATABASE_URL=...` scratch-DB usage line exactly as `concurrency_bench.py:28-31` does, and the script refuses to run without an explicit `--yes-scratch-db` style acknowledgement or an out-of-band `DATABASE_URL`. Cleanup deletes what it seeded.

---

## 5. The decision gate this ticket exists to settle

### 5.1 The index

Candidates, to be decided by measurement, not by assumption:

| Candidate | Helps | Cost |
|---|---|---|
| `(product_id, status)` | `_on_hand`'s point lookup — the ticket's stated hypothesis | one more index to maintain on every lot write |
| `(product_id, status) INCLUDE (quantity_on_hand)` | the same, but **index-only** — no heap fetch for the SUM | larger index |
| `(product_id)` alone | `list_alerts`' `GROUP BY` | narrower |

Note the paths disagree: `list_alerts` (`inventory_service.py:339-342`) has **no `WHERE`** and groups over the whole table, so a `(product_id, status)` index does little for it unless it covers `quantity_on_hand` and the planner picks an index-only scan. **Expect the honest answer to be per-query, and report it that way** rather than forcing one verdict.

### 5.2 RSK-04's periodic-snapshot fallback

Retire it if the measured p95 at scale 200 sits comfortably inside budget with the index; keep it, with the trigger volume named, if the curve is super-linear. Either way `docs/RISK_LOG.md:22` gets a number and a date instead of an assertion.

### 5.3 Where a fix is in scope

If — and only if — the EXPLAIN shows `export_csv` (`inventory_service.py:418-426`) materialising an unbounded result set that grows linearly with the table, note it as an availability risk. It has no `LIMIT` and no streaming. Adding a cap is a **separate ticket**; measuring and naming it belongs here.

---

## 6. Test plan

### Backend — `tests/integration/test_aggregation_at_volume.py` (needs a live DB)

| # | Case | Asserts |
|---|---|---|
| 1 | `availability` correctness at volume | `on_hand` / `reserved` / `available` exact against a known seeded fixture — the numbers must not change because an index was added |
| 2 | `availability` excludes released reservations at volume | the `status = 'active'` filter survives the index |
| 3 | `availability` isolated per `state` at volume | no cross-state bleed |
| 4 | `list_alerts` correctness at volume | `current_quantity` per product matches an independently computed SUM; `is_triggered` correct at the threshold boundary |
| 5 | `list_inventory` pagination stability at volume | page 1 ∪ page 2 has no duplicate and no gap — the `order_by(id)` guarantee at `inventory_service.py:41-46` |
| 6 | `export_csv` row count at volume | every lot appears exactly once; header row correct |
| 7 | Latency gate, evidence-derived budget | p95 of each path under the budget measured in §4, **not** a round number picked by hand |
| 8 | **Negative control** | with the index dropped, the plan for `_on_hand` is a seq scan; with it created, it is not. Asserted on `EXPLAIN` output, so the test proves the index is actually being used rather than merely present |

Case 8 is the one that makes this evidence rather than a number — it is the same mutation-verification discipline `test_worksheet_close_concurrency.py` uses.

### Backend — `tests/test_aggregation_bench.py` (no DB, runs in CI)

- Scale → expected-row-count planning is pure and correct.
- `EXPLAIN` output parsing correctly identifies `Seq Scan` vs `Index Scan` / `Index Only Scan`, including nested plan nodes.
- Curve assembly produces one entry per (path, scale, arm) and fails loudly on a missing cell rather than silently emitting a short curve.
- Artifact naming is stable (a changed name silently orphans the evidence).

### Coverage

`--cov=app.models.inventory` plus any new `app.*` module, ≥85% floor per `CONTRIBUTING.md`. Note that `scripts/validation/` is **not** under `app.*`, so the bench script itself is covered by `tests/test_aggregation_bench.py` for its pure logic rather than by the `app.*` floor.

### Frontend

**None.** No UI change.

### Playwright

The `next-ticket` skill asks for `frontend/e2e/ticket-NN.spec.ts`. There is no user-facing flow here — the honest artifact is a **regression guard**, not a new journey: assert the inventory list, availability and alerts endpoints still return correct data with the index in place (both locales unaffected, no console errors). See §9 open question 3.

---

## 7. Live verification

Backend-only, so "live" means the API and the evidence, not a click-through:

1. `docker compose up -d` (or local Postgres on the port that is actually free — `CLAUDE.md` documents 5433, local `.env` may be **5434**; check who holds it before starting).
2. `alembic upgrade head` → confirm `015` applies and `alembic downgrade -1` cleanly removes the index (reversibility is a `CONTRIBUTING.md` expectation and RSK-02's stated discipline).
3. `python scripts/seed_fake_data.py --scale 200`.
4. `PYTHONPATH=backend python scripts/validation/aggregation_bench.py validation-evidence --scales 1,10,50,200`.
5. Read the artifacts: plans flipped, curve shape, p95 at each scale.
6. `curl` the four endpoints with a real token; confirm responses are byte-identical before and after the index. **An index must not change an answer** — if any response moves, stop, that is a correctness bug in the query.
7. `./scripts/smoke-test.sh`.

---

## 8. Build order

1. Cut `ticket-45/aggregation-benchmark` from `origin/master`.
2. Stand up the DB, apply migrations, seed at `--scale 1`; confirm the four paths work before measuring anything.
3. **Capture the baseline EXPLAIN plans first, unindexed** — before writing any migration. If the planner does not seq-scan, the hypothesis is wrong and the ticket's shape changes; better to learn that in hour one.
4. Write `aggregation_bench.py` with its reservation seeding (Trap 1) and `ANALYZE` discipline (Trap 2), measuring at the service layer (Trap 3). Tests for its pure helpers alongside, per-feature.
5. Run the sweep unindexed across all scales. Record.
6. Add the index (ORM + migration `015`), `ANALYZE`, re-run. Record.
7. **Decide** — §5.1 per-query verdict, §5.2 fallback call. If the index does not win, the migration is deleted rather than landed, and the ticket's deliverable becomes the evidence that RSK-04 was overstated. That is a legitimate outcome.
8. Write `test_aggregation_at_volume.py`, including the case-8 negative control, with budgets derived from step 5/6 numbers.
9. Wire stage `6e` into `validation-run.sh`; update `RISK_LOG.md`, the readiness plan §8.1/§8.2, README.
10. Full gate: pytest + coverage, `npx jest`, `npm run lint`, `npm run build`, `./scripts/smoke-test.sh`, Playwright.
11. Draft PR, `Closes ACR-45`, noting the `015` revision claim vs the ledger (§1.5).

---

## 9. Risks / open questions

**Resolved by following an existing pattern — recorded here, not blocking:**

1. *Service-layer vs HTTP measurement* → service layer, per Trap 3. HTTP reported as context only.
2. *Where artifacts go* → `validation-evidence/`, gitignored, per ACR-43.
3. *Whether the bench asserts a budget* → no; the gate lives in the integration test, per `api_latency_bench.py:16-18`.
4. *Scratch-DB safety* → explicit acknowledgement flag + docstring contract, per `concurrency_bench.py`.

**Genuine risks:**

- **R1 — the hypothesis may not hold.** Postgres may seq-scan by choice at these volumes and be right to. The ticket is still valuable (it retires RSK-04 with evidence), but the headline changes from "we found and fixed it" to "we measured it and it was not there." Both are honest A8 outcomes; only one is a code change.
- **R2 — laptop noise.** A p95 on a dev machine under other load is unstable. Mitigation: 100 samples, warm-up discard, EXPLAIN plans as the primary categorical evidence, and the run's host recorded in `RunMetadata`.
- **R3 — scale 200 seed time.** ~14 400 lots through the async seed may be slow. If it is, cap the default sweep at 50 and run 200 once, manually, for the headline number — recording the asymmetry in the artifact rather than hiding it.
- **R4 — index write cost unmeasured.** Adding an index taxes every lot insert. The receiving path writes lots in bulk. If the index lands, a note on the write-side cost belongs in the writeup even if it is not separately benchmarked.

**Decided rather than escalated:**

- **D1 — Playwright scope.** ACR-45 adds no UI, so there is no new user journey to walk. Rather than invent one, `frontend/e2e/ticket-45.spec.ts` is a **regression guard**: inventory list, availability and alerts still render correct data with the index in place, in both locales, with a clean console. This follows the repo's own precedent — ACR-42 and ACR-43 were likewise backend-only and were verified by re-running the existing suite against the changed stack (95/95 and 89/89 respectively) rather than by adding a journey. Recorded here as a choice, not left open.

---

## 10. Definition of done

- [ ] Latency curves p50/p95/p99 across `--scale` steps, for all four paths, both arms
- [ ] `EXPLAIN (ANALYZE, BUFFERS)` plans captured before and after, per path
- [ ] A per-query decision on the `inventory_lots` index, with migration `015` if it wins — or a documented "it did not" if it does not
- [ ] Evidence-backed keep-or-retire call on RSK-04's periodic-snapshot fallback, written into `docs/RISK_LOG.md:22`
- [ ] Machine-readable artifacts under `validation-evidence/` via the ACR-43 harness
- [ ] Negative-control test proving the index is used, not merely present
- [ ] `validation-run.sh` stage 6e reproduces the whole thing from one command
- [ ] Full gate green; draft PR open; `plan_a8_a10_readiness.md` §8 updated
