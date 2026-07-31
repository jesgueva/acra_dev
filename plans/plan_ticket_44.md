# Plan — ACR-44 / A8-5: Comparative concurrency study (3-arm ablation)

**Ticket:** [ACR-44](https://linear.app/chronos-laboral/issue/ACR-44/a8-5-comparative-concurrency-study-3-arm-ablation)
**Branch:** `ticket-44/comparative-concurrency-study` (worktree cut from `origin/master` @ `d2e9520`)
**Refs:** `plans/plan_a8_a10_readiness.md` §2.3 (A8-5) · §4 · ISS-06 · SC-4 · ADR-02
**Depends on:** ACR-41 (A8-1 seed `--scale N`) ✅ · ACR-43 (A8-2/A8-3 harness) ✅ merged as #36

---

## 1. Current state

### 1.1 The harness this ticket must extend (landed in #36)

`backend/app/core/benchmark.py` is the measurement library. Its own module docstring, at
**lines 22–29**, pre-specifies this ticket:

> **Known extension point.** A sample is currently one number: elapsed seconds. […] A8-5's
> three-arm ablation additionally needs *retry rate* and *correctness* per arm, which this
> vocabulary cannot express — so it will want an outcome tag on `record()`/`time()` and a counter
> in `stats`. That is deliberately not built yet: the three drawdown implementations fail in
> different ways (optimistic-guard retry vs. SERIALIZABLE `40001` vs. unguarded lost update), and
> guessing the schema before one exists would over-fit it. **Extend here rather than starting a
> second measurement structure alongside this one.**

That is the design mandate, and it is not negotiable in this ticket. What exists today:

| Piece | Location | Note |
|---|---|---|
| `percentiles()` | `benchmark.py:60-81` | nearest-rank, `rank = ceil(p/100 × n)`; **`statistics.quantiles` deliberately not used** (`:18-20`) — changing method silently moves every published number |
| `RunMetadata.capture()` | `benchmark.py:132-152` | git SHA/tag/dirty, host, python, redacted DSN, UTC ts, exact command, free-form `**params` |
| `RunMetadata.header_lines()` | `benchmark.py:154-164` | mirrors `validation-run.sh`'s `hdr()` shape |
| `BenchmarkRun.record()` / `.time()` | `benchmark.py:184-197` | `time()` records **even when the block raises** (`finally`) |
| `BenchmarkRun.stats` | `benchmark.py:204-220` | `n/min/max/mean/p50/p95/p99` ms; `n` always reported by design (`:207-209`) |
| `BenchmarkRun.write()` | `benchmark.py:230-261` | `<name>.json` + `<name>.txt`; raw samples in JSON so a gate can recompute |

Consumer pattern to imitate: `scripts/validation/api_latency_bench.py` — argparse, `out_dir`
defaulting to `validation-evidence`, one `BenchmarkRun` per label, `WARMUP = 5` discarded samples
(`:74-76`), exit non-zero only on hard failure, never on a latency budget (`:15-17`).

Wiring: `scripts/validation-run.sh:106-111` is stage **6c**, and notes the script writes its own
provenance so no `hdr()` wrapper is applied.

### 1.2 The three arms — all three already in the tree

**Arm 1 — unguarded read-modify-write.**
`inventory_service.adjust_quantity:111-148`: reads the lot (`:118`), computes `new_qty` (`:120`),
assigns (`:127`), commits (`:146`). No `with_for_update()`, no version predicate.
`shipment_service.create_shipment` has the same shape — checks `lot.quantity_on_hand < item.quantity`
then decrements (`:103`, `:147-149`).

**Arm 2 — ADR-02 optimistic version guard + ascending-id row locks.**
`production_worksheet_service.close_worksheet:186-353`. Docstring `:192-216` states the protocol;
`docs/architecture.md:115-135` is ADR-02 itself. Steps: Read Committed (not SERIALIZABLE) → parent
row lock `:218-222` → atomic version guard judged by `rowcount` `:239-253` → ascending-id lot locks
`:272-281` → integer FIFO draw `:288-328` → one commit `:345`.

**Arm 3 — SERIALIZABLE.**
`allocation_service.allocate_materials:16-126`. `await db.rollback()` at `:29` then
`SET TRANSACTION ISOLATION LEVEL SERIALIZABLE` at `:30`, with `with_for_update()` at `:33` and `:69`.
The rollback exists because `require_privilege`'s three RBAC reads had already opened the
transaction, making the `SET` raise `ActiveSQLTransactionError` — **every allocation was a 500**.
`tests/integration/test_allocation_isolation.py:1-10` documents exactly that.

**ADR-02's untested claim is the study's target.** `architecture.md:119-122` asserts SERIALIZABLE
"aborts the losers with `could not serialize access`, which reaches the operator as a 500 and
**needs a retry loop to be usable at all**." No number backs "usable". That is what A8-5 supplies.

### 1.3 Existing concurrency test infrastructure

`backend/tests/integration/test_worksheet_close_concurrency.py` (TC-02) is the template — and it
already contains arm 1's shape as a **deliberate negative control** (`:224-270`) that drives an
unguarded read-modify-write and asserts it *does* lose an update. Reusable pieces:

- `sessionmaker_` fixture `:66-75` — `pool_size=PARALLEL_CLOSERS + 4`, `max_overflow=4`
- `_seed()` `:92-142` / `_teardown()` `:145-173` — owns exactly the rows it creates, uuid-suffixed
- `_on_hand()` `:176-184`, `_movements()` `:187-198` — correctness oracles
- `_run_close()` `:201-216` — **one session (hence one connection) per closer**; `:10-11` warns that
  sharing a session serializes the closers and "quietly delete[s] the race"
- `asyncio.Barrier` `:289` — releases every closer at the same instant
- `ABUNDANT_STOCK = 100_000` `:48-50` — so "insufficient stock" can never stand in for a real guard

`tests/integration/test_concurrency.py` is **mock-based** (`CONCURRENT_USERS = 20`) and, per TC-02's
docstring `:5-8`, "by construction, could never have detected a lost update." It is not a basis for
this study and will not be extended.

Live-DB guard convention: `tests/integration/test_seed_scaling.py:34-38` — module-level
`pytestmark = pytest.mark.skipif(not os.getenv("ACRA_SEED_IT_DSN"), ...)`.

---

## 2. The methodological decision

**The three arms operate on three different domain operations.** Arm 1 adjusts a lot, arm 2 closes
a worksheet, arm 3 allocates work-order materials. Benchmarking them as-is measures *how much work
each endpoint does*, not *how each concurrency control behaves* — the independent variable is
confounded on arrival, and the resulting table would be indefensible in the writeup.

**Plan: a controlled ablation on one workload.** Fix the workload — *N concurrent closers drawing
stock from one product* — and vary only the concurrency control:

| Arm | Control | Fidelity |
|---|---|---|
| `unguarded` | read-modify-write, no lock, no version predicate | reproduces `inventory_service.adjust_quantity` / `shipment_service.create_shipment`; identical in shape to TC-02's negative control `:224-270` |
| `optimistic` | ADR-02: row lock + `UPDATE … WHERE version = :expected` + ascending-id lot locks | **the real `close_worksheet`, called directly** — not a reproduction |
| `serializable` | `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE` + `FOR UPDATE`, no version guard | reproduces `allocation_service.allocate_materials:29-33` |

Arm 2 being the production function is what keeps this honest: the arm the project actually ships is
measured as it ships, and the other two are minimal faithful reductions of shapes that demonstrably
exist in the tree. Every arm consumes the same quantity from the same seeded scenario, so throughput
and retry-rate differences are attributable to the control alone.

**Arm 3 runs twice** — naked, and with a bounded retry loop on SQLSTATE `40001`. ADR-02's rejection
rests on "needs a retry loop to be usable at all"; measuring both is what turns that sentence from
an assertion into a finding. It is cheap: same driver, one wrapper.

---

## 3. Change list

### CREATE

| File | Purpose |
|---|---|
| `scripts/validation/concurrency_bench.py` | The runner. Seeds a scenario per (arm, level), releases N closers on an `asyncio.Barrier`, records per-attempt outcome + duration, asserts the correctness oracle, writes artifacts via `BenchmarkRun`. |
| `backend/tests/integration/test_concurrency_bench_arms.py` | Live-DB assertions that each arm behaves as claimed — env-guarded per §1.3. |

### MODIFY

| File | Change |
|---|---|
| `backend/app/core/benchmark.py` | The `:22-29` extension point: optional `outcome` tag on `record()`/`time()`, outcome counters + derived rates in `stats`, outcome block in both artifacts. **Backward compatible** — see §4. |
| `backend/tests/test_benchmark.py` | Extend with the outcome-vocabulary cases (§6.1). Keeps one home for harness tests rather than a parallel file. |
| `scripts/validation-run.sh` | Stage **6d**, mirroring 6c's no-`hdr()` treatment. |
| `plans/plan_a8_a10_readiness.md` | §8.1: A8-2/A8-3 → ✅ done, landed in `ticket-43/…` (#36); A8-5 → **ACR-44**, A8-6 → **ACR-45**. §8.2: evidence row for A8-2/A8-3. (User-requested; see §7.5 for the conflict risk.) |
| `docs/architecture.md` | ADR-02 §115-135 gains the measured numbers behind "needs a retry loop to be usable at all". |

### No schema change

No new model, no Alembic revision. The study reads and writes existing tables through existing
services and its own fixtures. (`architecture.md:112-113` records `013` as next-available — this
ticket does not consume it.)

---

## 4. Harness extension — the contract

Additive only. Every existing call site (`api_latency_bench.py:85-86`) must keep working untouched,
and **an artifact produced without outcomes must be byte-identical to one produced today** — A8-2's
numbers are already published in `validation-evidence/`, and silently reshaping the JSON would
invalidate them.

```python
run.record(seconds, outcome="conflict")     # outcome defaults to OK
with run.time(outcome="serialization_failure"):
    ...
```

- `Outcome` vocabulary: `ok` · `conflict` (deterministic 409) · `serialization_failure` (SQLSTATE
  `40001`) · `error` (anything else) · `lost_update` (correctness violation, set by the oracle).
- `stats` gains `outcomes: {name: count}` and derived `success_rate` / `retry_rate` / `error_rate`
  **only when at least one non-default outcome was recorded**; otherwise `stats` keeps its exact
  current seven keys.
- Latency percentiles stay computed over **all** attempts, with a separate `p*_ok_ms` over
  successes only — a fast failure is not a fast operation, and burying aborts in the same p50 is
  how a broken arm looks quick.

---

## 5. Runner contract

```
PYTHONPATH=backend python scripts/validation/concurrency_bench.py [OUT_DIR] \
    [--arms unguarded,optimistic,serializable,serializable-retry] \
    [--levels 2,4,8,16,32] [--rounds 5] [--stock 100000] [--draw 6000]
```

Per (arm, level): seed → barrier-release N closers on their own sessions → collect
`(outcome, duration)` → read the correctness oracle (`_on_hand` + `_movements`) → tear down. One
`BenchmarkRun` per (arm, level), plus a comparison artifact `concurrency-ablation.{json,txt}`.

Correctness oracle per round, reusing TC-02's assertions: expected on-hand is
`stock − winners × draw`, and movements must be exactly `[("consume", -draw)] × winners`. An arm
whose on-hand disagrees is recorded as `lost_update` — that is the study's headline column, and it
is what arm 1 is expected to produce.

Exit 0 on a completed sweep even when an arm loses updates: a lost update is the **finding**, not a
runner failure. Non-zero only on setup/teardown failure, per `api_latency_bench.py:15-17`.

---

## 6. Test plan

### 6.1 Pure unit — `backend/tests/test_benchmark.py` (no DB, counts toward the 85% `app.*` floor)

- `record()`/`time()` default to `ok` when no outcome is passed
- explicit outcomes tally correctly; `time()` tags the sample even when the block raises
- `success_rate` / `retry_rate` / `error_rate` arithmetic, including the all-failures case
- **regression guard:** a run with no explicit outcomes yields `stats` with exactly the current
  seven keys, and `as_dict()` matches the pre-change shape
- `p*_ok_ms` present only when successes exist; empty-success run does not raise
- unknown/invalid outcome rejected with `ValueError`, matching `record()`'s existing negative-sample
  guard (`benchmark.py:186-187`)
- `percentiles()` untouched — existing cases must stay green

### 6.2 Live-DB integration — `test_concurrency_bench_arms.py` (env-guarded)

One test per arm, asserting the claim the writeup will make:

- `unguarded` at 8 closers **loses at least one update** — on-hand > expected. Asserted, not
  observed: if this ever comes back clean the whole study is asleep (TC-02 `:13-15` makes the same
  argument for the same reason).
- `optimistic` at 8 closers: exactly one 200, seven 409, on-hand exact, movements exactly one
  `consume`. Mirrors TC-02 `:278-319`.
- `serializable` at 8 closers: aborts surface as SQLSTATE `40001`, and on-hand is still exact —
  correct but hostile, which is precisely ADR-02's claim.
- `serializable-retry`: bounded retry converts aborts into successes; assert the retry counter is
  non-zero, so the arm is proven to have actually retried rather than won on timing.
- Deterministic sweep at `--levels 2 --rounds 1` completes and writes both artifact files.

### 6.3 Frontend

**None.** This ticket adds no UI, no endpoint, and no schema. See §7.2 — the e2e spec the
`next-ticket` flow normally mandates has nothing to assert here.

### 6.4 Gate

`pytest` (≥85% on `app.core.benchmark`), `npx jest`, `npm run lint`, `npm run build`,
`./scripts/smoke-test.sh`. Frontend gates are unaffected-but-run, to prove nothing regressed.

---

## 7. Risks / open questions

### 7.1 — RESOLVED IN PLAN: controlled ablation over native call sites
§2. Comparing three different domain operations would confound the independent variable. Fixed
workload, arm 2 is the real `close_worksheet`, arms 1 and 3 are faithful reductions. **Flagging for
the user because it is the ticket's central methodological choice** — the Linear description says
"measure all three", and this plan measures all three *shapes* on one workload rather than three
endpoints on three workloads.

### 7.2 — DECISION NEEDED: no Playwright surface
The `next-ticket` flow mandates a committed `frontend/e2e/ticket-NN.spec.ts` plus live browser
exploration. **This ticket has no user-facing surface** — it is a benchmark script, a library
extension, and two docs. A spec here could only assert that unrelated pages still load, which is
noise that later readers must maintain. **Recommendation: skip the e2e spec, state the omission in
the PR body.** The alternative — asserting the app still boots — is already covered by
`scripts/smoke-test.sh` in the gate.

### 7.3 — CI darkness, and not repeating the seed-module coverage hole
The live-DB tests in §6.2 will be **skipped in CI** exactly like `test_seed_scaling.py`, which is
what currently pins the seed module at 40%. Mitigation is structural: all DB-driving code lives in
`scripts/validation/` (outside the `app.*` coverage floor) and only pure, fully-unit-testable logic
goes into `app/core/benchmark.py`. So the skipped tests cost **no** `app.*` coverage. Wiring the
guarded suites into CI remains A10-3's job, not this ticket's.

### 7.4 — Runtime budget
4 arms × 5 levels × 5 rounds = 100 scenarios, each seeding and tearing down. At 32 closers the
`sessionmaker_` pool must scale (`pool_size = level + 4`) and Postgres `max_connections` (default
100) becomes the ceiling. Mitigation: `--rounds` defaults to 3 for the sweep with 5 reserved for the
committed evidence run; the runner asserts pool headroom before starting a level rather than failing
half-way through.

### 7.5 — `plans/plan_a8_a10_readiness.md` §8 is a known conflict hotspot
ACR-42 and ACR-36 are editing the same section on open branches, and #36 already merged **without**
updating its own §8.1 rows — which is why they are stale now. The edits here are small and
line-local (four table rows + one §8.2 row) to keep the conflict trivially resolvable.

### 7.6 — Postgres port
`CLAUDE.md` documents 5433; local `backend/.env` may be on 5434 and 5433 is often squatted by
another stack. Check what actually holds the port and export `DATABASE_URL` to match reality before
running anything. The study must **not** run against the dev database — it seeds and deletes; it
follows `test_seed_scaling.py:14`'s dedicated-scratch-DSN precedent.

### 7.7 — Arm 1 is expected to be *fastest*
The unguarded arm takes no locks, so it will very likely post the best throughput while being the
only incorrect arm. The comparison artifact must put the correctness column **first**, or the table
reads as an endorsement of the broken implementation.

---

## 8. Build order

1. Extend `app/core/benchmark.py` with the outcome vocabulary (§4); unit tests alongside, including
   the byte-identical-artifact regression guard. Gate: `pytest tests/test_benchmark.py --cov=app.core.benchmark`.
2. `scripts/validation/concurrency_bench.py` — scenario seed/teardown + oracle, lifted from TC-02's
   helpers; one arm only (`optimistic`, the real service) end to end, at `--levels 2 --rounds 1`.
3. Add the `unguarded` arm; confirm it loses updates. This is the negative control — nothing after
   this is trustworthy until it fails the way it should.
4. Add `serializable` and `serializable-retry`; confirm `40001` surfaces and the retry counter moves.
5. Full sweep 2/4/8/16/32; write the comparison artifact.
6. Live-DB integration tests (§6.2).
7. `validation-run.sh` stage 6d.
8. Docs: ADR-02 numbers in `architecture.md`; `plan_a8_a10_readiness.md` §8.1/§8.2.
9. Full gate (§6.4), then draft PR.

---

## 9. Live verification

1. Start a **scratch** Postgres (not the dev DB) and `alembic upgrade head`.
2. `python backend/scripts/seed_fake_data.py --scale 10` for volume.
3. `PYTHONPATH=backend python scripts/validation/concurrency_bench.py --levels 2,4,8 --rounds 2` —
   confirm it completes, prints a per-arm summary, and writes `concurrency-ablation.{json,txt}`
   plus per-(arm,level) pairs under `validation-evidence/`.
4. Open the `.txt`: provenance header matches `validation-run.sh`'s shape, correctness column first.
5. Confirm `unguarded` shows lost updates and `optimistic` does not — at every level.
6. Re-run `api_latency_bench.py` and diff its artifact against a pre-change run to prove the
   harness extension changed nothing for existing consumers.
7. `./scripts/validation-run.sh /tmp/ve-check` — stage 6d runs and does not break 6c.
