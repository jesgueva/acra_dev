# Plan — ACR-41 / A8-1: Parameterized seed (`seed_fake_data.py --scale N`)

**Linear:** [ACR-41](https://linear.app/chronos-laboral/issue/ACR-41/a8-1-parameterized-seed-seed-fake-datapy-scale-n)
**Status:** approved → implemented. Measured results in §9.
**Parent:** [`plan_a8_a10_readiness.md`](./plan_a8_a10_readiness.md) §2.3, item A8-1
**Written against:** `master` @ `7649a6e`
**Branch:** `ticket-41/parameterized-seed`
**Date:** 2026-07-30
**Size:** S — roughly half a day

**Why this is first:** A8-5 (concurrency study), A8-6 (aggregation bench) and A8-2 (benchmark
harness) all state "at volume" as a precondition. Today nothing in the repo can produce volume, so
this is the only item in Part A with no upstream dependency and two downstream ones.

---

## 1. Verified current state

Measured against `backend/scripts/seed_fake_data.py` (856 lines), not recalled.

### 1.1 There is no CLI at all

`seed_fake_data.py:855` is `if __name__ == "__main__": asyncio.run(seed_fake_data())`. No `argparse`,
no env knob, no parameters anywhere. The docstring (`:4`) documents exactly one invocation.

### 1.2 What one run produces, exactly

| Rows | Count | Where it is fixed |
|---|---|---|
| Roles | 4 | `ROLE_DEFINITIONS` `:53` |
| Users | 5 | `USER_SPECS` `:116` |
| Contacts | 6 suppliers + 4 carriers | `SUPPLIERS` `:198`, `CARRIERS` `:207` |
| Products (raw) | 6 | `RAW_MATERIALS` `:159` |
| Low-stock alerts | 6 | one per raw material `:804` |
| Delivery notes + deliveries | **24** | `for index in range(1, 25)` `:480` |
| Delivery items | **72** | `item_count = 2 + (index % 3)` `:518` → cycles 3, 4, 2 over 24 indices = 8 × 9 |
| Raw inventory lots | **72** | one per delivery item `:543` |
| Inventory transactions | **72** | one `receive` per lot `:561` |
| Work orders | **8** | `WORK_ORDER_SEEDS` `:228` |
| Work-order materials | **21** | 3+3+3+3+2+2+2+3 across the 8 seeds |
| Finished-goods lots | **2** | statuses `completed` + `ready_for_shipment` `:728` |
| Material allocations | variable | greedy lot walk `:596`, 6 of 8 work orders allocate |

### 1.3 The good news — the generator is already pure in `index`

Every per-delivery value is an arithmetic function of `index` and `offset` alone. No `random`, no
`uuid`, no clock beyond `date.today()`:

```python
supplier_name     = SUPPLIERS[(index - 1) % len(SUPPLIERS)]              # :492
carrier_name      = CARRIERS[(index - 1) % len(CARRIERS)]                # :493
delivery_date     = today - timedelta(days=index * 2)                    # :491
item_count        = 2 + (index % 3)                                      # :518
material          = RAW_MATERIALS[(index + offset - 1) % len(...)]        # :522
pallets           = 2 + ((index + offset) % 8)                           # :523
units_per_pallet  = 100 + (((index * 3 + offset) % 10) * 50)             # :524
```

**Consequence:** widening `range(1, 25)` to `range(1, 24 * scale + 1)` is sufficient for the delivery
axis, and indices 1–24 keep producing byte-identical rows. Scale N is a strict **superset** of
scale 1. That is what makes this a small ticket rather than a rewrite.

### 1.4 The three real traps

1. **Work orders are keyed on `product` name.** `create_demo_work_orders` skips on
   `select(WorkOrder.id).where(WorkOrder.product == spec.product)` (`:682`). Replicating
   `WORK_ORDER_SEEDS` verbatim means every replica after the first is silently skipped — you would
   get 8 work orders at any scale and never notice. Replica names must be suffixed.

2. **Allocation raises rather than degrades.** `allocate_inventory` (`:612`) throws
   `RuntimeError("Not enough seeded inventory…")` when the lot pool runs short, aborting the whole
   seed. Supply and demand both scale by N so the aggregate ratio holds, but the greedy walk drains
   lots front-first across *all* replicas of a material — this needs empirical confirmation, not a
   ratio argument.

3. **One transaction, one commit, everything resident.** `seed_fake_data` accumulates the entire
   graph in a single session and commits once at `:827`. At N=100 that is ~7 200 lots + 7 200 items
   + 7 200 transactions + 2 400 notes/deliveries ≈ 30 k objects in the identity map, inside one
   long-lived transaction.

### 1.5 Performance shape today

Per delivery: 1 `SELECT` existence check (`:483`) + 3 `flush()` calls. At N=100 that is ~2 400
round-trips for the existence checks alone, all of which could be a single pre-fetch.

### 1.6 Consumers that must not break

`grep seed_fake_data` (excluding `node_modules`, `.git`) hits: `README.md`, `CONTRIBUTING.md`,
`docs/architecture.md`, `frontend/e2e/helpers.ts`, `frontend/e2e/helpers/auth.ts`,
`frontend/e2e/README.md`, `backend/tests/test_shipping_privileges.py`,
`backend/alembic/versions/013_shipping_privileges.py`, `scripts/reset-db-and-seed.sh`.

**All 83 Playwright tests log in as seeded users and read seeded rows.** Any drift in the scale-1
fixture breaks the e2e suite. This is the dominant risk on the ticket.

`scripts/validation-run.sh:72` calls `./scripts/reset-db-and-seed.sh` as stage 3/7 of the evidence
harness — so the scale knob has to reach through that script too, or A8-5 cannot use it.

### 1.7 No test covers the seed script

`backend/tests/` has 24 test modules; none of them exercise `seed_fake_data.py`.
`test_shipping_privileges.py` asserts *seeded privileges* against a live DB, which is adjacent but
does not touch the generator.

---

## 2. Design

### 2.1 Split "what to create" from "write it"

The one structural change. Extract pure planning functions above the DB layer:

```python
@dataclass(frozen=True)
class DeliveryItemSpec:
    material_type: str
    lot_prefix: str
    storage_location: str
    pallets: int
    units_per_pallet: int
    quantity_x100: int

@dataclass(frozen=True)
class DeliverySpec:
    index: int
    bol_reference: str
    supplier: str
    carrier: str
    delivery_date: date
    items: tuple[DeliveryItemSpec, ...]

def plan_deliveries(scale: int, today: date) -> list[DeliverySpec]: ...
def plan_work_orders(scale: int) -> list[WorkOrderSeed]: ...
```

`create_demo_deliveries` / `create_demo_work_orders` then consume specs instead of computing them
inline. This is what makes scale-1 fidelity testable without a database — the golden-snapshot test
in §4.1 is the regression lock protecting the 83 e2e tests, and it runs in milliseconds.

### 2.2 Replica naming

- **Deliveries** — nothing to do. `DEMO-BOL-{year}-{index:03d}` stays unique past index 999
  (`:03d` pads to a *minimum* of 3, so 1000 → `"1000"`), and `lot_number` derives from it (`:545`).
- **Work orders** — replica `r` (0-indexed) of base seed `s` gets `product = s.product` when `r == 0`
  and `f"{s.product} #{r + 1}"` otherwise. Replica 0 keeping the bare name is what preserves scale-1
  fidelity and the superset property.
- **Finished-goods lots** — `DEMO-FG-{work_order.id:04d}` (`:729`) keys on the DB id. Already unique.

### 2.3 CLI surface

```
python scripts/seed_fake_data.py [--scale N] [--deliveries N] [--work-orders N] [--json]
```

| Flag | Default | Purpose |
|---|---|---|
| `--scale N` | `1` | Multiplier on both volume axes. `N=1` must be bit-identical to today. |
| `--deliveries N` | derived | Absolute override — A8-6 wants lots without work-order demand |
| `--work-orders N` | derived | Absolute override, same reason inverted |
| `--json` | off | Emit the summary as JSON instead of prose — direct input to A8-2's run metadata |

Reject `--scale < 1` at the argparse layer.

**Deliberately not adding `--seed`.** The generator has no RNG today and should not acquire one;
determinism without a seed value is strictly better for A10's reproducibility criterion.

`--json` should carry `{scale, elapsed_seconds, counts: {...}, database_url_host, git_sha}` — the
elapsed number is itself an A8-2 input.

### 2.4 Cheap performance wins (do these, they are in-scope)

1. Replace the per-delivery existence `SELECT` (`:483`) with one pre-fetch of existing
   `DEMO-BOL-%` document numbers into a `set`. Removes 24N round-trips for a few lines.
2. Leave the flush structure alone initially — ids are genuinely needed.

**Not in scope until measured:** bulk inserts, `--batch-size` commit chunking. §5 sets the budget
that would trigger them.

### 2.5 Reach-through

- `scripts/reset-db-and-seed.sh:72` → `"$PY" scripts/seed_fake_data.py "$@"`, plus a usage line
  documenting `./scripts/reset-db-and-seed.sh --scale 25`.
- Module docstring `:4-15`, `README.md`, `CONTRIBUTING.md`, `docs/architecture.md`,
  `frontend/e2e/README.md` — one line each on the new flag and on scale-1 being the e2e contract.

---

## 3. Files touched

| File | Change |
|---|---|
| `backend/scripts/seed_fake_data.py` | argparse + `plan_deliveries` / `plan_work_orders` extraction + batched existence pre-check + `--json` summary |
| `scripts/reset-db-and-seed.sh` | forward `"$@"`; usage comment |
| `backend/tests/test_seed_scaling.py` | **new** — pure planning tests, no DB |
| `backend/tests/integration/test_seed_scaling.py` | **new** — live-DB volume + idempotence (see §6.2) |
| `README.md`, `CONTRIBUTING.md`, `docs/architecture.md`, `frontend/e2e/README.md` | document `--scale` |
| `plans/plan_a8_a10_readiness.md` | flip A8-1 to ✅ in §8, add the §8.2 row |

No migration. No app-code change. No API change.

---

## 4. Tests

### 4.1 `backend/tests/test_seed_scaling.py` — pure, no database

1. **Golden snapshot at scale 1.** `plan_deliveries(1, date(2026, 7, 30))` → 24 specs / 72 items,
   compared field-by-field against a frozen literal. *This is the test that protects the 83
   Playwright specs.*
2. **Superset property.** `plan_deliveries(N, D)[:24] == plan_deliveries(1, D)` for N in 2, 10.
3. **Volume scales linearly.** `len(plan_deliveries(N, D)) == 24 * N`; item total `== 72 * N`.
4. **Key uniqueness.** All `bol_reference` distinct at N=50; all `product` names distinct across
   `plan_work_orders(50)`.
5. **Work-order fidelity.** `plan_work_orders(1) == list(WORK_ORDER_SEEDS)` — exact identity,
   including material tuples.
6. **Quantity integrality.** Every `quantity_x100` is an `int` — guards the `×100` convention
   against float drift at scale.
7. **Argparse rejects** `--scale 0` and `--scale -1`.

### 4.2 `backend/tests/integration/test_seed_scaling.py` — live Postgres

Follows the `test_reservation_availability.py` contract (module-level DSN from env, `async with`
setup rather than an async fixture — see that file's docstring on the `MissingGreenlet` event-loop
trap).

1. Seed at scale 2 on a clean DB → assert 48 notes / 144 items / 144 lots / 16 work orders /
   42 work-order materials.
2. Re-run at scale 2 → asserts **zero** new rows (idempotence).
3. Re-run at scale 3 → adds exactly the increment (24 notes, 8 work orders), leaves scale-2 rows
   untouched.
4. No `RuntimeError` from `allocate_inventory` at scale 2 and 10 — trap §1.4.2, verified rather
   than argued.

**Guard:** this test necessarily writes global fixture data, unlike every other integration test
which cleans up after itself. It must **skip unless an explicit `ACRA_SEED_IT_DSN` is set**, so it
can never clobber a developer's working database. See open question §7.2.

### 4.3 Regression gate before merge

- `pytest backend/tests/ -v` — full 354 must stay green.
- `npx playwright test` from `frontend/` against a scale-1 reseed. Non-negotiable: §4.1 proves the
  *plan* is unchanged; only the e2e run proves the *rows* are.

---

## 5. Verification and the numbers to record

Capture these — they are A8-2's first data points, not just a smoke check:

| Check | Expected |
|---|---|
| `reset-db-and-seed.sh` (no args), row counts vs. a pre-change capture | identical, every table |
| wall clock at `--scale 1` | baseline |
| wall clock at `--scale 10` (240 deliveries / 720 lots) | ≲ 10× baseline |
| wall clock at `--scale 50` (1 200 deliveries / 3 600 lots) | **budget: under 2 minutes** |
| peak RSS at `--scale 50` | recorded; informs whether §2.4's batching is needed |

If `--scale 50` misses the 2-minute budget, that is the trigger for bulk inserts and
`--batch-size` commit chunking — as a follow-up, not a scope expansion here.

---

## 6. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Scale-1 fixture drift breaks all 83 e2e tests** | §4.1 golden snapshot + §4.3 full Playwright run before merge |
| R2 | `allocate_inventory` RuntimeError at scale (§1.4.2) | §4.2.4 asserts it empirically at N=2 and N=10 |
| R3 | Single transaction blows up at high N (§1.4.3) | §5 measures it; batching is a measured follow-up |
| R4 | `delivery_date = today - index*2 days` walks ~13 years back at N=100 | Cosmetic; see open question §7.3 |
| R5 | Integration test clobbers a dev database | §4.2 skip guard on `ACRA_SEED_IT_DSN` |

---

## 7. Decisions taken at the approval gate

All three resolved in favour of the lean, and implemented.

1. **The material catalogue scales** — `--materials M` generates `Synthetic Material 007…` past the
   6 named types. A8-6's per-`(item, state)` `GROUP BY` (RSK-04) needs products, not just lots.
   Verified: `--materials 60` yields 60 products all carrying lots.

2. **The integration test ships behind an `ACRA_SEED_IT_DSN` skip guard.** It writes global fixture
   data and does not clean up, unlike every other integration test, so it must never point at a
   developer's working database by accident. A10-3 wires the DSN into CI; until then it is dark, and
   that is recorded as a known gap rather than hidden.

3. **The delivery-date window wraps** to `(index % 365) * 2`. Indices 1–24 are unaffected, so the
   demo fixture is untouched; only cost is duplicate dates, which carry no uniqueness constraint.

---

## 8. Out of scope

- The benchmark harness that consumes this seed — that is **A8-2**.
- Any change to scale-1 fixture *content* (adding materials, users, statuses).
- Bulk-insert rewrite or commit chunking, unless §5's budget is missed.
- `backend/scripts/create_admin.py` — its privilege-name drift is **A10-5**.

---

## 9. Measured results

Captured on a dedicated Postgres 15 container (`acra-pg-acr41`, host port 5441), macOS, Python
3.13. These numbers are A8-2's first inputs, not just a smoke check.

### 9.1 Scale-1 fidelity — the acceptance criterion

Row counts alone would miss field-level drift, so the fixture was captured **before** the change,
then re-captured on a freshly migrated database **after** it, comparing a SHA-256 of every table's
full ordered content:

| Table | Rows | Content hash |
|---|---|---|
| roles · users · contacts · products | 4 · 5 · 10 · 6 | unchanged |
| role_privilege_assignments | 45 | unchanged |
| low_stock_alerts | 6 | unchanged |
| delivery_notes · deliveries | 24 · 24 | unchanged |
| delivery_items | 72 | unchanged |
| inventory_lots · inventory_transactions | 74 · 72 | unchanged |
| work_orders · work_order_materials | 8 · 21 | unchanged |
| material_allocations | 16 | unchanged |

**All 14 tables bit-identical.** The 83 Playwright specs read the same rows they did on `7649a6e`.

### 9.2 Volume and timing

| Run | Deliveries | Lots | Work orders | Allocations | Elapsed |
|---|---|---|---|---|---|
| `--scale 1` | 24 | 74 | 8 | 16 | 1.4 s |
| `--scale 50` | 1 200 | 3 700 | 400 | 805 | **8.9 s** |
| `--scale 200` | 4 800 | 14 800 | 1 600 | 3 243 | **31.8 s** |
| `--scale 20 --materials 60 --work-orders 0` | 480 | 1 440 | 0 | 0 | 3.1 s |

Budget was "`--scale 50` under 2 minutes"; actual is 8.9 s, and 4× the volume costs 3.6× the time —
close enough to linear that the §2.4 bulk-insert/batching follow-up is **not needed**. Recorded here
so A8-2 does not re-derive it.

### 9.3 Idempotence and increment

- Re-running `--scale 1` on a seeded database creates **0** rows in every table.
- Raising to `--scale 2` creates exactly one more unit: +24 deliveries, +72 items, +72 lots,
  +8 work orders, +21 work-order materials, +16 allocations, +2 finished-goods lots.

### 9.4 The allocation trap (§6 R2), settled with numbers

`material_balance` makes worst-case supply/demand visible from the plan alone:

| Configuration | Worst supply/demand |
|---|---|
| `--scale 1` | 176× |
| `--scale 50` | 165× |
| `--deliveries 24 --work-orders 200` | 7.1× |
| `--deliveries 24 --materials 60` | 4.9× |
| `--deliveries 24 --work-orders 200 --materials 60` | **0.20× — aborts** |

Headroom is essentially flat from scale 1 to 50, which is the ratio-preservation argument confirmed
rather than assumed. `--materials` dilution is real but far weaker than feared: it needs to be
combined with a large `--work-orders` before anything starves. When it does, the seeder exits 1
with a message naming the knobs to turn, and commits nothing.

### 9.5 A ceiling the optimisation introduced, and removed

§2.4's batched existence pre-check — one `IN` query replacing 24N round-trips — quietly imposed a
scale ceiling that the per-row `SELECT` it replaced did not have. asyncpg binds one parameter per
`IN` element and the PostgreSQL wire protocol caps a statement at **32 767** of them.

Measured against this schema: a 24 000-element `IN` succeeds; 65 000 raises `InterfaceError`. At 24
delivery references per scale unit that puts the failure somewhere around **`--scale 1365`** — past
anything benchmarked here, but a confusing driver-level error rather than an honest limit.

Fixed by chunking both pre-checks at 10 000 (`_existing_values`), which keeps the round-trip saving
without the ceiling. Two integration tests cover it: one drives 40 000 references through the query,
the other proves chunking does not *lose* rows, since the pre-check is what makes re-seeding
idempotent.

Found by probing the limit directly rather than by review — worth noting because the same trap
applies to any other `IN`-batched lookup added for A8-5/A8-6.

### 9.6 Deviation from the plan

§2.4 proposed keeping the existing flush structure and optimising only if the budget was missed. The
budget was met by a wide margin (8.9 s against 120 s), so no further optimisation was done — the
only performance change that shipped is the chunked existence pre-check above.
