# Plan — A8 / A10 Readiness

**Status:** draft for review
**Written against:** `master` @ `7649a6e` (`ticket-21: T21 — End-to-End Tests (Playwright) (#33)`)
**Date:** 2026-07-30
**§8 board last reconciled against Linear + GitHub:** 2026-08-01, `master` @ `fbf1703`
(`ticket-45: A8-6 — aggregation benchmark at volume (RSK-04) (#44)`). Every A8/A10 work item is now
either merged or explicitly not-started (⬜) — nothing is mid-flight.

Briefs: [`08_Midpoint_Technical_Evidence_Review/brief.md`](../../acra_docs/assignments/08_Midpoint_Technical_Evidence_Review/brief.md) ·
[`10_Artifact_Hardening_Reproducibility_Check/brief.md`](../../acra_docs/assignments/10_Artifact_Hardening_Reproducibility_Check/brief.md)

This plan answers one question: **what still has to be built before A8 and A10 can be written
honestly?** It is not a feature plan. Items are scoped to what the two rubrics actually reward.

---

## 1. Verified baseline (master @ `7649a6e`)

Measured, not recalled:

| Signal | Value |
|---|---|
| Backend tests | **354** collected |
| Backend coverage | 94% at last capture · **85% floor, CI-only** |
| Jest | **20 files / 135 tests** — CI runs **3 files** |
| Playwright | **13 specs / 83 tests** — CI runs **0** |
| API routes | **62** |
| Alembic revisions | **14**, strictly linear, one head (`014`) |
| Seed volume | ~24 deliveries / ~72 lots, **hard-coded, no `N`** |

**Two structural facts drive this whole plan:**

1. **The ledger does not exist.** `009_stock_movement_ledger_placeholder.py` is still the only
   migration that names `stock_movements`, and it is still a no-op. `stock_movement_service.py`
   still raises `NotImplementedError`. The concurrency-safe close (ACR-30) operates on
   `InventoryLot`.
2. **There is no measurement infrastructure of any kind.** No profiler, benchmark tool, load
   generator, request-timing middleware, `/metrics`, structured logging, or scalable seed. Nothing
   in `backend/requirements.txt` or `frontend/package.json`. Master added *tests*, not
   *measurements*.

### What already exists and scores well

Do not rebuild these — cite them.

- **`tests/integration/test_worksheet_close_concurrency.py`** — 8 parallel closers × 5 rounds
  against real Postgres, with a deliberate **negative control** asserting the unguarded shape *does*
  lose an update, plus a mutation-verification table in the docstring. This is the most rigorous
  artifact in the repo.
- **`tests/integration/test_allocation_isolation.py`** (new on master, ACR-21) — proves
  `allocate_materials`' `SET TRANSACTION ISOLATION LEVEL SERIALIZABLE` **500'd on every real
  request**, because `require_privilege` had already opened the transaction. The mocked
  `test_allocation.py` no-ops the SET and could never catch it. This is empirical evidence against
  one arm of the ADR-02 comparison.
- **`tests/integration/test_reservation_availability.py`** — a real p95 < 200 ms gate over 200 lots
  (RSK-04). Thin, but genuine.
- **`scripts/validation-run.sh`** — 7-stage evidence harness with provenance headers on every
  artifact (git SHA, tag, host, exact command).
- **83 Playwright tests** across auth, inventory, locale, mobile, OCR, production-planning,
  receiving, work-orders, shipping, delivery notes.

---

## 2. Part A — A8, Midpoint Technical Evidence Review

**Rubric:** Implementation Maturity 10 · Testing/Benchmarking/**Comparative** 20 · Technical
Reasoning & Error Handling 20 · Evidence Packaging 20 · Recorded Walkthrough 20 · AI Usage Log 10.

The brief is explicit that this hard stop is *"driven by evidence quality rather than by feature
accumulation."* So the deliverable is the measurement apparatus, not more surfaces.

### 2.1 The stated technical question

A8 requires **one** question framing the package. Proposed:

> **Does the ACRA MES stock-drawdown path stay correct and interactive under concurrent
> production load, and does the AI receiving extractor meet a stated accuracy bar across real
> document layouts?**

Two subsystems, one claim each, both traceable to declared success criteria (SC-4, SC-2) and both
already carrying open risks (RSK-01, RSK-03). Each gets a comparison baseline, which is what the
20-pt criterion asks for.

### 2.2 Decision gate — build the ledger first, or not?

This is the one call that changes the shape of the package. **It is the open question for review.**

RSK-01 is deliberately still *Mitigating*, not Resolved: ADR-02's zero-row `FOR UPDATE` gap means
the close protocol is proven for the **lot model** and does not automatically transfer to the
ledger. So benchmarking today's close means measuring code the design docs say is being replaced.

| Option | Cost | Consequence |
|---|---|---|
| **A — Land the ledger first** *(recommended)* | +3–5 days | Evidence is about the architecture you keep. Removes the Implementation Maturity risk (10 pts: *"beyond prototype status in the key technical pathways"*). Unblocks ACR-29/31 and is needed for A10 and 99 regardless. |
| **B — Defer the ledger** | 0 | A8 is still passable, but the limitation must be stated explicitly and prominently. A grader who reads `target_schema.md` will find it; better to name it than be caught. A8 does reward naming *"limitations of the current evidence itself."* |

Scope of the ledger migration if Option A (per `reference/target_schema.md` §3):
`stock_movements` + `locations` (D-01) + `production_lines` (D-04); convert the three work-order
tables to `Integer ×100` (Q3); `delivery_note_id INTEGER NOT NULL REFERENCES delivery_notes(id)`;
migrate `LotStatus` (lifecycle) and reservation states to the material axis **together** — doing one
without the other reopens the seam (§7). Next free revision is **`015`**.

### 2.3 Work items

| # | Item | Rubric hook | Size | Depends on |
|---|---|---|---|---|
| **A8-1** | Parameterized seed — `seed_fake_data.py --scale N` | Nothing can be measured at volume today | S | — |
| **A8-2** | Benchmark harness — run metadata (git SHA, host, env, params), p50/p95/p99, machine-readable output under `validation-evidence/` | "Record methods so the run can be repeated"; Evidence Packaging 20 | S/M | — |
| **A8-3** | Request-timing middleware + structured request logs (status, route, duration, request id) | The entire **API** row of the tools table | S | — |
| **A8-4** | **OCR accuracy + provider comparison bench** | Testing/Comparative 20; API row; closes RSK-03 / ISS-05 / KI-09 | M/L | — |
| **A8-5** | **Comparative concurrency study** | Testing/Comparative 20; Technical Reasoning 20; SC-4 | M | A8-1, A8-2 |
| **A8-6** | Aggregation benchmark at volume (RSK-04) | Success-criteria linkage §3.1 | S/M | A8-1, A8-2 |
| **A8-7** | Subsystem diagram marking where each measurement was taken | Explicit "Architectures" deliverable — `docs/` currently has **zero** diagrams | S | A8-4…A8-6 |

**Total: ≈7–9 days**, plus 3–5 if Option A.

#### A8-4 — OCR accuracy + provider comparison (highest value)

SC-2 promises *"field-level line-item accuracy ≥ the v6 baseline."* **No such number exists
anywhere in the repo.** Current state:

- No BOL corpus. `find` for `*.pdf` / `*bol*` / `*fixture*` returns nothing.
- `test_ocr.py` is 10 tests, **100% mocked**, zero accuracy assertions.
- `scripts/validation/ocr_roundtrip.py` runs **one** synthetic document, **prints without
  asserting** (no `sys.exit(1)`), and never runs in CI.
- `ticket-21-ocr.spec.ts` stubs the endpoint with
  `Buffer.from("not-a-real-image-the-endpoint-is-stubbed")`.
- **`confidence` is `filled_header_fields / 4`** — a fill rate, not accuracy. Four *wrong* header
  values score 1.0.

Build:
1. A labelled corpus of BOLs spanning layouts (gridded, borderless/cramped, rotated, multi-page,
   Spanish-language, poor scan). Synthetic is acceptable and redistributable; add real client
   layouts only if licensing permits (see A10-6).
2. Field-level scorer with ground truth — header fields *and* line items, with fuzzy alignment
   rather than the current positional `got_items[gi]` match.
3. **`gemini-2.5-flash` vs `claude-sonnet-4-6` head-to-head** on accuracy and latency. This is the
   comparison baseline the rubric wants, and the fallback chain already makes both reachable.
4. Latency distribution, schema-validation, retry and error-case tests → the API evidence row.
5. An **asserted** no-regression gate with a recorded baseline number.

Replace or supplement the misleading `confidence` field, and say so in the writeup.

#### A8-5 — Comparative concurrency study

`ISS-06` records that **three divergent stock-drawdown implementations coexist right now**:

| Shape | Where |
|---|---|
| Unguarded read-modify-write | `inventory_service.adjust_quantity`, `shipment_service.create_shipment` |
| ADR-02 optimistic version guard + ascending-id row locks | worksheet close |
| SERIALIZABLE | `allocation_service` — the approach ADR-02 **rejected**, and which `test_allocation_isolation.py` proves was 500'ing in the real request path |

That is a three-arm ablation already sitting in the codebase, with one arm's failure already
documented. Measure all three for **correctness and throughput/retry-rate** at 2 / 4 / 8 / 16 / 32
concurrent closers, on the same seeded volume, and you have a genuine comparative study on the
project's load-bearing correctness claim. Extend the existing harness rather than starting fresh.

---

## 3. Part B — A10, Artifact Hardening and Reproducibility

**Rubric:** Artifact Completeness 20 · Reproducibility & Setup 20 · QA/Testing/Hardening 20 ·
README & Packaging 20 · Recorded Walkthrough 10 · AI Usage Log 10.

Foundation is already good: README is 219 lines with a real quickstart, both `.env.example`
templates are tracked, **no secret was ever committed** (verified across all branch history),
migrations are linear, and every relative markdown link resolves.

### 3.1 Work items

| # | Item | Why | Size |
|---|---|---|---|
| **A10-1** | **Dockerfiles for backend + frontend**; compose brings up the whole stack | No Dockerfile exists anywhere; `docker compose up` starts Postgres **only**. "Container spec" + clean-run environment are explicit deliverables | M |
| **A10-2** | **OCR offline/mock mode + committed sample fixtures** | Brief asks for "mock fallback instructions". Today the OCR path is unrunnable without a paid API key. Shares the corpus with A8-4 | S/M |
| **A10-3** | **CI: Playwright job, all 20 Jest files, frontend coverage gate** | 17/20 Jest files and **all 83 e2e tests never run in CI**. Written-but-unrun tests read worse than fewer tests. QA/Hardening 20 | M |
| **A10-4** | Lockfile + version reconciliation | Root `.nvmrc`=**22** contradicts `frontend/.nvmrc`=**24** and `engines.node>=24`. Python is 3.11/3.12/3.13 across README/architecture/CI. No lockfile, no `requires-python`. **`google-genai>=1.0.0` and `anthropic>=0.40.0` are unpinned** — the two least deterministic deps | S |
| **A10-5** | Privilege-parity test (seed vs migrations); fix or delete `create_admin.py` | It grants privilege names the routers don't enforce (`work_order.view` vs `work_orders.*`) and defaults to port **5432**. A new user running it gets an authenticated but privilege-starved "admin" | S |
| **A10-6** | LICENSE + data-provenance doc | No LICENSE anywhere. `frontend/acra_logo.png` is a client logo with no attribution or redistribution terms. Brief requires "what cannot be redistributed" | S |
| **A10-7** | README: Troubleshooting, expected-output transcript, hardware assumptions; runbook + packaging diagram | Named failure mode is *"a README that describes the project conceptually but omits concrete run steps."* `grep -i troubleshoot` over all docs returns **zero hits** | S/M |
| **A10-8** | Repo hygiene | `backend/.coverage` — a 68 KB SQLite binary — is **tracked** since `8efcbad` despite being in `.gitignore`, so it churns as a binary diff on every test run. Five stray `t19-*`/`t30-*` PNGs at repo root, none ignored. `plans/` half-tracked with no policy. `validation-evidence/` referenced by README:112 but absent | S |

**Total: ≈4–5 days**, then the assignment's own clean-environment pass and friction log — which
A10-1 is what makes tractable.

---

## 4. Sequencing

```
A8-1 seed(N) ──┬── A8-2 bench harness ──┬── A8-5 concurrency study ──┐
               │                        └── A8-6 aggregation bench ──┤
               │                                                     ├── A8-7 diagram ── A8 writeup
A8-3 timing middleware ──────────────────────────────────────────────┤
A8-4 OCR corpus + comparison ────────────────────────────────────────┘
        │
        └──────────► A10-2 offline OCR fixtures (same corpus)

[Option A] ledger migration 015 ── carry ADR-02 protocol ── feeds A8-5

A10-4 versions ── A10-1 Docker ──┬── clean-env pass ── friction log ── A10 writeup
                  A10-3 CI ──────┤
                  A10-5…A10-8 ───┘
```

**Deliberate overlaps** — do not duplicate:

- A8-2's run-metadata harness and A10-1's container are the same reproducibility story.
- A8-4's labelled corpus **is** A10-2's offline fixture set.
- A8-3's structured logging supports both the API evidence row and A10's QA criterion.

## 5. Out of scope

- **ACR-29 / ACR-31 + a Production Worksheet UI** (≈4–6 days). Neither the A8 nor the A10 rubric
  requires them. **Revisit before 99** (§9) — CSMS 2.1 requires that essential features be
  *implemented or explicitly identified as incomplete*, which makes deferring them a documented
  decision rather than a silent omission.
- **ACR-32** (Forklift Worksheet), **ACR-40** (master-data privileges).
- Any `Contact`→`Partner` / `Product`→`Item` rename — decided against in `target_schema.md` §1.1.

## 6. Open decisions

1. **§2.2 — Option A or B on the ledger.** Everything else in Part A is unaffected either way.
2. ~~**A8-4 corpus** — synthetic only or synthetic + real client BOLs?~~ **DECIDED 2026-07-30
   (ACR-36): synthetic only.** Redistributable, ships in-repo, runs in CI, and doubles as A10-2's
   offline fixture set with no licensing caveat for A10-6. Ships as a deterministic *generator +
   labels* rather than committed binaries, per `CONTRIBUTING.md:78`. Consequence to state in the A8
   writeup: synthetic BOLs are cleaner than real phone photos, so the measured accuracy is an
   **upper bound**.
3. **A10-3** — run Playwright on every PR, or nightly plus pre-tag? 83 tests at `workers: 1` with no
   `webServer` block will need a compose-based service setup either way.

## 7. Corrections to carry into the docs

Found while writing this; small, but they will read as drift if a grader hits them:

- **`ACR-31`'s Linear description is stale.** It still says to write *"inventory adjustment entries
  capturing `actual − planned`"*, but `target_schema.md` Q1 decided that delta is a **computation,
  never a movement** — writing it double-decrements stock.
- `plans/plan_ticket_35.md` says the shipping-privilege grants landed in migration `012` (lines
  **117, 192, 254** — the `:234` reference in the original draft has drifted); they landed in
  `013_shipping_privileges.py`.
- ~~`backend/alembic.ini:6` carries a stale `sqlalchemy.url` on port **5432**.~~ **Retired by ACR-42
  (`098cc2e`)** — it now reads 5433, at line 8.
- `acra_docs` has an unstaged `07_` → `08_` folder rename plus three untracked assignment folders.

**Corrections to this plan itself**, found while re-measuring for ACR-42 (2026-07-30):

- **A10-4 overstates the lockfile gap.** `frontend/package-lock.json` **is** tracked. It is the
  *backend* that has no lockfile — `requirements.txt` with unpinned `google-genai>=1.0.0` and
  `anthropic>=0.40.0` is the whole dependency spec. Scope A10-4 to the backend accordingly.
- **A10-8 overstates the stray-PNG problem.** `git ls-files` shows the `t19-*` / `t30-*` PNGs are
  **untracked**, not tracked — they pollute `git status` but were never committed. The only tracked
  PNG is `frontend/acra_logo.png` (which is A10-6's provenance problem, not A10-8's). The genuinely
  tracked-despite-`.gitignore` file is `backend/.coverage`, and that part of the item stands.

---

## 8. Progress

Running status of every item in this plan. Update the row when an item lands, and record the
evidence it produced — §8.2 is what the A8 and A10 writeups cite, so an item is only "done" once
it has an artifact or a merged commit behind it.

Legend: ⬜ not started · 🔄 in progress · ✅ done · ⏸️ blocked/deferred

### 8.1 Status board

| # | Item | Ticket | Status | Landed in |
|---|---|---|---|---|
| §2.2 | **Ledger decision gate** — Option A (build `015`) vs B (defer) | — | ⬜ open decision | — |
| A8-1 | Parameterized seed — `seed_fake_data.py --scale N` | **ACR-41** | ✅ done — `--scale/--deliveries/--work-orders/--materials/--json`, scale-1 proven bit-identical | `8027c14` ([PR #35](https://github.com/jesgueva/acra_dev/pull/35)) |
| A8-2 | Benchmark harness — run metadata, p50/p95/p99, machine-readable output | **ACR-43** | ✅ done — `app/core/benchmark.py`, nearest-rank percentiles + `RunMetadata` provenance, paired JSON/text artifacts; first consumer `api_latency_bench.py`; `validation-run.sh` stage 6c | `d2e9520` ([PR #36](https://github.com/jesgueva/acra_dev/pull/36)) |
| A8-3 | Request-timing middleware + structured request logs | **ACR-43** | ✅ done — `app/core/observability.py`, folded into A8-2 | `d2e9520` ([PR #36](https://github.com/jesgueva/acra_dev/pull/36)) |
| A8-4 | OCR accuracy + provider comparison bench | **ACR-36** | ✅ done — 7-layout labelled corpus, fuzzy line-item scorer, asserted no-regression gate; retires KI-09's anecdotal claim with a measured one; plan at `plans/plan_ticket_36.md`. Three follow-ups landed: can't-fail gate fixes for the validation script's swallowed exit code + an ambiguous-date scoring bias (#41), converged the bench onto ACR-43's shared `benchmark.py` percentile convention and closed a stranded-commit gap (#47), and a CI-only cross-host PNG byte-identity fix that had left master red (#49) | `8b84f9a` ([PR #40](https://github.com/jesgueva/acra_dev/pull/40)) + [#41](https://github.com/jesgueva/acra_dev/pull/41) + [#47](https://github.com/jesgueva/acra_dev/pull/47) + [#49](https://github.com/jesgueva/acra_dev/pull/49) |
| A8-5 | Comparative concurrency study (3-arm ablation) | **ACR-44** | ✅ done — 4-arm sweep; ADR-02 the only arm holding 100% success and 0 lost updates at 2→32. Plan at `plans/plan_ticket_44.md`. Two follow-ups landed: a two-directional over-consumption oracle + self-certifying contention witness + root-caused the barrier flake (#39), and a SERIALIZABLE abort-misclassification fix plus command-redaction hardening (#45) | `0547b38` ([PR #38](https://github.com/jesgueva/acra_dev/pull/38)) + [#39](https://github.com/jesgueva/acra_dev/pull/39) + [#45](https://github.com/jesgueva/acra_dev/pull/45) |
| A8-6 | Aggregation benchmark at volume (RSK-04) | **ACR-45** | ✅ done — migration `015` adds `(product_id, status) INCLUDE (quantity_on_hand)`. **RSK-04 was half-mitigated and nobody had checked:** `stock_reservations` was indexed in revision 010, `inventory_lots` carried nothing but its PK. **Result: 14.134 ms → 0.029 ms server-side at 200 000 lots (487×), `Seq Scan` → `Index Only Scan` at every volume.** RSK-04 **Resolved**, its snapshot fallback retired. **New risk RSK-10** opened: `export_csv` unpaginated/unstreamed, 2 782 ms p95 at 200k lots — the slowest path in the system, deliberately not fixed here. pytest 533/96%, Jest 146/146, Playwright 100/100 | `fbf1703` ([PR #44](https://github.com/jesgueva/acra_dev/pull/44)) |
| A8-7 | Subsystem diagram marking measurement points | — | ⬜ | — |
| A10-1 | Dockerfiles for backend + frontend; whole-stack compose | **ACR-42** | ✅ done — `backend/Dockerfile` + `frontend/Dockerfile`; compose is now `db` → `migrate` → `backend` → `frontend` (+ `seed` profile) | `098cc2e` ([PR #37](https://github.com/jesgueva/acra_dev/pull/37)) |
| A10-2 | OCR offline/mock mode + committed sample fixtures | — | ⬜ | — |
| A10-3 | CI: Playwright job, all 20 Jest files, frontend coverage gate | **ACR-46** | ✅ done — Playwright now runs as a required-cadence CI job (every PR, matching the other two) against the A10-1 containerized stack, seeding the scale-1 fixture; all 20 Jest files run via `test:coverage` with a coverage gate pinned to the measured baseline rounded down (statements 60% / branches 55% / functions 45% / lines 65%). **Resolves the §6 #3 open decision** (every-PR, not nightly). Review-loop follow-up landed: CONTRIBUTING.md drift fix + the e2e job's container-name/port-var isolation hardened (#48). No branch-protection/required-check exists on the repo for any CI job yet — flagged, not fixed, as out of ticket scope | `97a6555` ([PR #43](https://github.com/jesgueva/acra_dev/pull/43)) + [#48](https://github.com/jesgueva/acra_dev/pull/48) |
| A10-4 | Lockfile + Node/Python version reconciliation, pin AI SDKs | **ACR-42** | ✅ done — one Node (24) and one Python (3.13) named repo-wide; `backend/requirements.lock` pins 57 packages. Folded into A10-1 | `098cc2e` ([PR #37](https://github.com/jesgueva/acra_dev/pull/37)) |
| A10-5 | Privilege-parity test (seed vs migrations); fix/delete `create_admin.py` | (ACR-40 adjacent) | ⬜ | — |
| A10-6 | LICENSE + data-provenance doc | **ACR-47** | ✅ done — `LICENSE` (MIT, code only) + `docs/DATA_PROVENANCE.md` explicitly carving out `frontend/acra_logo.png` | `308c46b` ([PR #46](https://github.com/jesgueva/acra_dev/pull/46)) |
| A10-7 | README troubleshooting, expected-output transcript, runbook | — | ⬜ | — |
| A10-8 | Repo hygiene (untrack `backend/.coverage`, `plans/` policy) | **ACR-48** | ✅ done — untracked `backend/.coverage` (68 KB SQLite binary, tracked since `8efcbad` despite `.gitignore`, was churning as a binary diff on every local test run; stays on disk, stays ignored); documented the `plans/` policy in CONTRIBUTING.md — gitignored going forward as review scratch space, the 12 already-committed `plan_ticket_*.md` files grandfathered in and still tracked. The item's other two original complaints (stray root PNGs, missing `validation-evidence/`) were already resolved by `9f72293` (ticket-19), predating this ticket | `bf36b55` ([PR #50](https://github.com/jesgueva/acra_dev/pull/50)) |
| §7 | Doc corrections (ACR-31 description, plan_ticket_35 `012`/`013`, alembic.ini, `acra_docs` rename) | — | 🔄 **1 of 4 retired** — alembic.ini's stale 5432 fixed by ACR-42; the other three stand | `098cc2e` (partial) |

**A10-4 is folded into A10-1 under one ticket** (ACR-42): a correct Dockerfile cannot be written
before the Node and Python versions are settled, and §4 already sequences A10-4 → A10-1. Splitting
them would mean writing the images twice.

**A8-3 is folded into A8-2 under one ticket** (ACR-43): both are §2.3 items with **no dependencies**,
both are the same missing thing — §1's "no measurement infrastructure of any kind" — and the timing
middleware is the in-process source the harness reports on. §4 already runs them into the same
convergence point. Splitting them would mean defining the run-metadata and percentile conventions
twice.

**§8 is the only shared surface in this file, and it does conflict in practice.** Checked at
reconcile time: `ticket-42/docker-stack-versions` and `ticket-36/ocr-accuracy-bench` add only their
own `plans/plan_ticket_NN.md` and leave this file alone — but `ticket-44/concurrency-ablation` (PR
#38) carried its own §8.1 and §8.2 edits inside the feature branch, and collided head-on with this
reconcile pass. Both sides had written the same rows differently and the merge had to be resolved by
hand. So: land §8 edits as their own small commit against fresh `master` rather than carrying them
inside a feature branch, and **append** to §8.2 rather than rewriting neighbouring rows.

### 8.2 Completed

When an item lands, append a row here rather than only flipping §8.1 — the evidence column is what
makes the writeup citable.

| # | Item | Merged (UTC) | Commit / PR | Evidence produced |
|---|---|---|---|---|
| **A8-1** | Parameterized seed (ACR-41) | 2026-07-31 | `8027c14` — [PR #35](https://github.com/jesgueva/acra_dev/pull/35), merged from `ticket-41/parameterized-seed` | See `plans/plan_ticket_41.md` §9. **Scale-1 fixture proven bit-identical** across all 14 seeded tables (per-table SHA-256 of full ordered content, captured before/after on freshly migrated databases) — the contract the 83 Playwright specs depend on. **Volume/timing:** scale 50 = 1 200 deliveries / 3 700 lots / 400 work orders in **8.9 s**; scale 200 = 14 800 lots in **31.8 s**; ~linear, so the planned bulk-insert follow-up is unnecessary. **Idempotence:** re-seeding creates 0 rows; raising the scale adds exactly one unit. **Supply/demand headroom** 176× at scale 1 vs 165× at scale 50 — the ratio-preservation claim measured, not assumed. 40 pure tests + 6 guarded live-DB tests. **Caveat:** the live-DB tests are skipped unless `ACRA_SEED_IT_DSN` is set, which CI never sets — so the seed module sits at 40% covered in CI. Wiring that in is A10-3's. |
| **A8-2 + A8-3** | Benchmark harness & request-timing middleware (ACR-43) | 2026-07-31 | `d2e9520` — [PR #36](https://github.com/jesgueva/acra_dev/pull/36), merged from `ticket-43/bench-harness-request-timing` | `app/core/benchmark.py` — nearest-rank p50/p95/p99 defined once (`ceil(p/100 × n)`, no interpolation, **pinned against a known vector**, so every published number is an observation that happened), plus `RunMetadata` provenance: git SHA/tag/dirty, host, Python, database, UTC timestamp, exact command. Credentials stripped from the recorded DSN, asserted against both artifacts. Every run writes `<name>.json` (raw samples, so a later gate recomputes rather than trusts) + `<name>.txt` (the `validation-run.sh` `hdr()` header shape). `app/core/observability.py` — one structured line per request (method, **route template**, status, `duration_ms`, request id), `X-Request-ID` echoed and CORS-exposed, `LOG_FORMAT=json` opt-in. New `validation-run.sh` stage + `scripts/validation/api_latency_bench.py` produce real artifacts: 5 endpoints × 100 requests, `/health` p50 **0.7 ms** / p95 1.2 ms, `/api/v1/deliveries` p50 **11.1 ms** / p95 16.5 ms / p99 31.2 ms. **Retires the hand-rolled percentile index** in `test_reservation_availability.py`. pytest **405 passed** (was 354), **95%** coverage, all three new/changed core modules **100%**; Jest 20 suites / **146**; **Playwright 89/89**; smoke PASSED. Zero new dependencies. Three limitations documented rather than hidden — a 500's `X-Request-ID` is unreadable cross-origin (built above CORS), `BenchmarkRun` has no retry-rate axis yet **for A8-5 to extend**, and `BaseHTTPMiddleware` costs two task spawns per request. |
| **A10-1 + A10-4** | Containerize the stack & pin runtime versions (ACR-42) | 2026-07-31 | `098cc2e` — [PR #37](https://github.com/jesgueva/acra_dev/pull/37), merged from `ticket-42/docker-stack-versions` | `docker compose up -d --build` brings the whole stack up from a clean clone: **0 → 2 Dockerfiles**, and services go from `db` only to `db` → `migrate` → `backend` → `frontend` (+ a `seed` profile). Plan at `plans/plan_ticket_42.md`. **Version drift closed:** Node named 4 ways (root `.nvmrc` 22, `frontend/.nvmrc` 24, `engines` >=24, `@types/node` ^22) → **one (24)**; Python named 3 ways (README ≥3.11, docs 3.13, CI 3.12) → **one (3.13**, declared in `backend/pyproject.toml`). `backend/requirements.lock` pins the **57-package** transitive closure; `google-genai` and `anthropic` were previously unpinned and **not theoretically** — two dev virtualenvs built from the same `requirements.txt` were measured running `anthropic` 0.119.0 and 0.109.2. `backend/tests/test_packaging.py` holds these as **30 negative-controlled assertions**, each failing with a message naming the offending file. **The design constraint worth citing:** `NEXT_PUBLIC_API_URL` is baked into the browser bundle at build time and must be host-reachable (`localhost:8000`), while `BACKEND_URL` is read at runtime by the auth proxy and must be the service name (`backend:8000`) — wire them the same way round and the stack reports healthy while every login fails. `scripts/compose-smoke.sh` asserts both directions, including grepping the shipped JS chunks to prove the internal hostname never reached the browser. Gates per the PR: pytest **384 passed / 94.59%**, Jest 20 suites / **146**, `next build` ok across the `@types/node` 22→24 bump, host smoke PASSED, compose smoke passed, **Playwright 91/91 against the containerized stack**. Also swept up: a duplicated `CORS_ORIGINS` in `backend/.env.example` (the file a clean-run user copies), `reset-db-and-seed.sh` / `smoke-test.sh` bare `docker compose up -d` now scoped to `db`, and `alembic.ini`'s stale 5432 — which retires one of §7's carried corrections. |
| **A8-5** | Concurrency ablation — optimistic locking under contention (ACR-44) | 2026-07-31 | `0547b38` — [PR #38](https://github.com/jesgueva/acra_dev/pull/38), merged from `ticket-44/concurrency-ablation`; follow-ups [#39](https://github.com/jesgueva/acra_dev/pull/39) → `56bfaf5` and [#45](https://github.com/jesgueva/acra_dev/pull/45) → `a356ea7` | Plan at `plans/plan_ticket_44.md`. **Four arms** — `unguarded` (read-modify-write), `optimistic` (ADR-02's version guard), `serializable`, `serializable-retry` (+5 bounded retries) — over a workload held fixed at N concurrent closers drawing from one product, so the isolation control is the only variable. 5 rounds per cell, `--stock 1000000 --draw 1000`, PostgreSQL 15.18, concurrency 2→32. **The headline:** `unguarded` loses **281 updates** across the sweep and completes 3% of attempts at 32; **ADR-02 is the only arm holding 0 lost updates *and* 100% success at every level**, and the only arm whose goodput *rises* with load (95 → **227** ops/s). `serializable` also loses nothing but completes 3% at 32 (156 → 52); +5 retries buys 21% (237 → 77). **Why the study reports goodput, not throughput:** bare `serializable` posts the sweep's highest raw attempt rate (**1648 attempts/s** at 32) while finishing 3% of the work — raw throughput would have ranked the worst arm first. Extends `benchmark.py` **strictly additively at the extension point ACR-43 named** (`benchmark.py:22-29`): `Outcome`, per-outcome counts, success/retry/error rates, `p*_ok_ms`. Gates: pytest **466 passed / 10 skipped / 92%**, `benchmark.py` **100%**, Jest 20 suites / 146. 13 harness unit tests + 3 pure oracle tests + 5 live-DB arm tests, the latter **guarded per-test rather than per-module** — a module-level `pytestmark` would take the harness tests dark too, which is the trap currently pinning the seed module at 40%. Caught a real flake in the process: the barrier guarantees closers *start* together but not that they *overlap*, so a round could silently assert nothing; rounds are now pooled, 8/8 clean repeats. **Deliberately not done:** no Playwright spec, and `unguarded` is left unfixed in `inventory_service.adjust_quantity` / `shipment_service.create_shipment` — the numbers are the argument for that follow-up. Live-DB arm tests stay skipped in CI until A10-3. **#39** made the correctness oracle two-directional (over-consumption, not just lost updates), made the optimistic-arm test self-certifying by running the unguarded arm first as a contention witness, and root-caused the barrier flake to SERIALIZABLE's snapshot-timing racing `asyncio.Barrier`. **#45** fixed a SERIALIZABLE abort-misclassification and hardened command redaction against credentials appearing in the provenance line. |
| **A8-4** | OCR accuracy + provider comparison bench (ACR-36) | 2026-07-31 | `8b84f9a` — [PR #40](https://github.com/jesgueva/acra_dev/pull/40), merged from `ticket-36/ocr-accuracy-bench`; follow-ups [#41](https://github.com/jesgueva/acra_dev/pull/41) → `f6b1d43`, [#47](https://github.com/jesgueva/acra_dev/pull/47) → `048ad12`, [#49](https://github.com/jesgueva/acra_dev/pull/49) → `441fc07` | `backend/scripts/ocr_bench/` — deterministic Pillow-rendered corpus (7 labelled layouts: gridded, borderless_cramped, rotated, multipage, spanish, poor_scan, **degraded_fax**), fuzzy line-item alignment (`difflib.SequenceMatcher`, 0.75 threshold) fixing the positional-alignment defect where one dropped row shifted every later comparison. Fixed two defects on the way: `confidence` was a **fill rate** not accuracy — kept for the 422/fallback trigger it already gates, supplemented with an honestly-named `header_fill_rate` and a `provider` field that was computed and thrown away. **Retires KI-09's anecdotal claim with a measured one:** the 7-layout corpus shows `borderless_cramped` scoring the same as `gridded` on both providers — layout alone no longer degrades extraction — but `degraded_fax` (downscaled/grainy/skewed) produces genuine misreads on both (a BOL reference and an item name both hallucinated). **Baseline** (`tests/fixtures/ocr/baseline.json`, 3 rounds × 7 docs, 0.05 tolerance): gemini-2.5-flash header 96.25% / item-F1 99.25%, claude header 96.43% / item-F1 97.1%. **Caught a real quota bug measuring it:** `gemini-2.5-pro` returns `429 RESOURCE_EXHAUSTED` in ~142ms on every call on this API key — flash is the default, pro is one env var away for when quota exists. Asserted no-regression gate (`test_ocr_accuracy.py`, `OCR_BENCH_LIVE=1`) with a negative control in both directions. **Caveat stated, not buried:** synthetic BOLs are cleaner than a real phone photo, so these figures are an upper bound; real-corpus validation stays open under RSK-03. Gates: pytest 95 passed / 2 skipped on the touched suites (591 passed full-suite, 8 pre-existing live-DB failures unrelated — no Postgres in that environment); Jest 20 suites / 148; lint 0 errors; build OK. **#41** fixed two can't-fail defects found on review: `validation-run.sh` set `OCR_FAILED=1` but never read it (no `set -e`, so a failed gate still exited 0), and `parse_date` guessed ambiguous DD/MM vs MM/DD dates instead of refusing them — 3 of 7 corpus documents had exactly that date shape, so the bias sat on real recorded numbers. **#47** converged the bench onto `app.core.benchmark.percentiles` (ACR-43's shared convention), deduplicated the three ruled layouts' rendering code, and applied `cached_property`/`lru_cache` fixes measured at 16×, 6×, and 10× redundant calls respectively. **#49** fixed the fallout: `#47`'s own drift-guard test asserted the committed sample PNG matches a fresh render byte-for-byte, which `corpus.py` documents as **not** holding cross-host (macOS Arial vs CI Linux DejaVu/Liberation) — split into a portable structural check (valid PNG, exact canvas size) plus the byte-exact check `skipif`'d off the reference-font host. |
| **A10-3** | CI: Playwright job, all 20 Jest files, frontend coverage gate (ACR-46) | 2026-07-31 | `97a6555` — [PR #43](https://github.com/jesgueva/acra_dev/pull/43), merged from `ticket-46/ci-playwright-jest-coverage`; follow-up [#48](https://github.com/jesgueva/acra_dev/pull/48) → `b3b42ef` | CI ran 3/20 Jest files (`--no-coverage`) and 0/99 Playwright specs before this. `frontend` job now runs the full 20-file Jest suite via `npm run test:coverage` with a coverage gate pinned to the *measured* baseline rounded down to the nearest 5 (statements 60% / branches 55% / functions 45% / lines 65%; real numbers were 64.14/58.44/49.25/65.88%) — confirmed the gate actually fails by temporarily raising it above the real number, then set it back. New `e2e-playwright` job brings up the A10-1 containerized stack under a distinct project/ports so it can't collide with a concurrent run, seeds the scale-1 fixture the specs assume, runs the full Playwright suite, uploads the HTML report as an artifact on any outcome, and tears down. Runs on every PR, same cadence as the other two jobs — **resolves the open §6 #3 decision** (nightly would hide regressions until later, and the rubric wants evidence on the PR a grader looks at). Gates: pytest 600 passed/17 skipped/95.22% (no backend code touched), Jest 20/20 files, 148 tests, lint 0 errors, build OK, local dry-run of the exact job logic — **99/99 Playwright specs passed** against the containerized stack. No branch-protection/required-check exists on the repo for any CI job (verified via the GitHub API, 404 on `branches/master/protection`) — flagged as a separate decision, not made unilaterally. **#48** closed two review-loop gaps that shipped when #43 merged while still under review: CONTRIBUTING.md still described the old 3-file Jest allowlist and said nothing about the new `e2e-playwright` job; and the job's own comment claimed the full `compose-smoke.sh` isolation/diagnostics pattern but only implemented part of it — container-name isolation was port-only (`docker-compose.yml` pins an explicit `container_name:` per service, which `-p`/project-name does not namespace, so matching `ACRA_*_CONTAINER` overrides were added), the base-URL env vars re-typed port numbers as string literals instead of referencing the vars that control them, and no failure-diagnostics step existed for a stack-level failure before Playwright even runs. Neither gap was a live bug on GitHub's single-job-per-VM runners, but both were latent. |
| **A10-6** | LICENSE + data-provenance doc (ACR-47) | 2026-07-31 | `308c46b` — [PR #46](https://github.com/jesgueva/acra_dev/pull/46), merged from `ticket-47/license-data-provenance` | Plan at `plans/plan_ticket_47.md`. Found the repo is **public on GitHub** with no LICENSE anywhere — so the pre-existing state was stricter than intended for the student's own code (no reuse grant at all) and looser than intended for the one genuinely client-owned asset (`frontend/acra_logo.png`, committed since `8efcbad`/ACR-17, no attribution ever attached). Resolved as `LICENSE` (MIT, code only) + `docs/DATA_PROVENANCE.md`, which explicitly excludes the logo from the grant and inventories what's already-synthetic (seed data, the ACR-36 OCR corpus, demo credentials) with cross-links rather than duplicated text. `frontend/package.json` and `backend/pyproject.toml` given matching `license` fields. Docs-only — no app code touched. Gate: `./scripts/smoke-test.sh` PASSED end to end (DB → migrate → seed → backend boot → auth/RBAC → 34-test pytest subset → `next build`) on a dedicated scratch Postgres, confirming the diff is inert. |
| **A10-8** | Repo hygiene — untrack `backend/.coverage`, document `plans/` policy (ACR-48) | 2026-08-01 | `bf36b55` — [PR #50](https://github.com/jesgueva/acra_dev/pull/50), merged from `ticket-48/repo-hygiene` | Untracked `backend/.coverage` (68 KB SQLite binary, tracked since `8efcbad` despite `.gitignore`, was churning as a binary diff on every local test run) — stays on disk, stays gitignored. Added `plans/` to `.gitignore` going forward and documented the policy in CONTRIBUTING.md: new plan files are review scratch space, deleted once a ticket ships, per the global planning-process convention; the 12 already-committed `plan_ticket_*.md` files (cited as evidence throughout this progress table) are grandfathered in and stay tracked — an ignore rule doesn't untrack them. Reconciled against current master first: the original item's other two complaints — stray root PNGs, `validation-evidence/` referenced but absent — were already resolved by `9f72293` (ticket-19), predating this ticket; no action needed there. Docs/hygiene-only, no application code touched. |
| **A8-6** | Aggregation benchmark at volume (ACR-45) | 2026-08-01 | `fbf1703` — [PR #44](https://github.com/jesgueva/acra_dev/pull/44), merged from `ticket-45/aggregation-benchmark` | Plan at `plans/plan_ticket_45.md`. **RSK-04 was half-mitigated and nobody had checked.** `stock_reservations` was indexed in revision 010; `inventory_lots` carried nothing but its primary key, so the `_on_hand` half of every `availability()` call sequentially scanned the table while the `_reserved` half used an index. `scripts/validation/aggregation_bench.py` sweeps four read paths × 4 volumes (1k/10k/50k/200k lots) × 2 arms, calling the **real service functions** and running `EXPLAIN` on the statement the service actually issued (captured off the engine, so a published plan cannot drift from the query). Migration **015** adds `(product_id, status) INCLUDE (quantity_on_hand)`. **Result: 14.134 ms → 0.029 ms server-side at 200 000 lots (487×), `Seq Scan` → `Index Only Scan` at every volume.** The shape is the finding, not the ratio: unindexed cost grows with the table (2.9 → 2.6 → 3.9 → 14.1 ms) while indexed cost is flat (0.034 → 0.038 → 0.009 → 0.029 ms). **RSK-04 Resolved and its periodic-snapshot fallback retired** — a flat sub-0.05 ms aggregate has no degradation curve to defend against. **Reported honestly rather than overclaimed:** the index does not change the plan for `list_alerts` (no `WHERE`, still `Seq Scan` at every volume; 45.6 → 29.7 ms at 200k) and nothing for `list_inventory` (already index-only on the PK). **New risk found: RSK-10** — `export_csv` is unpaginated and unstreamed, 1 507 ms p95 at 50k lots and **2 782 ms p95 at 200k**, the slowest path in the system by an order of magnitude. **Three methodology traps documented and avoided**, each of which yields a plausible benchmark that proves nothing: the seed creates **zero** reservations at any `--scale` (so the naive comparison is against an empty table), PostgreSQL plans from `pg_statistic` so `ANALYZE` must follow every volume and DDL change, and wall-clock time here is transport-bound — the index made p95 wall time *worse* at 10k lots while the query itself got 140× faster, which is why the decision was made on server-side execution time. pytest **533 passed, 15 skipped, 96%**; Jest **146/146**; lint 0 errors; **Playwright 100/100**; smoke **7/7 PASSED**; migration `015` verified reversible. Negative control (`test_index_is_used_not_merely_present`) drops the index inside a transaction, asserts the plan degrades, and rolls back — and its fixture had to be reshaped to be *selective*, because an earlier version made one product 23% of the table, where PostgreSQL correctly prefers a sequential scan regardless. |

---

## 9. Downstream — Final Applied Project (99)

Added because §5's deferral of ACR-29/31 now rests on 99's requirements rather than on A12/A14.
`12_Draft_Report_Final_Test_Evidence/` and `14_Final_Integrated_Submission_Presentation_demo/` were
empty placeholder directories (never tracked — git does not track empty dirs) and have been removed;
[`99_FINAL_APPLIED_PROJECT/brief.md`](../../acra_docs/assignments/99_FINAL_APPLIED_PROJECT/brief.md)
is the culminating submission.

**This is not a work plan for 99 — it is the dependency note that keeps §5 honest.**

### 9.1 A8 and A10 are 99's two largest inputs

Not detours. A8 produces **CSMS 2.2** almost wholesale; A10 produces the brief's Task 6
(readable/traceable/executable code) and Task 12 (final archive checklist) almost wholesale.

### 9.2 Coverage of 99's seven rubric criteria

Threshold is 3.0 (Proficient) on each; 4.0 is Advanced.

| Criterion | State | Note |
|---|---|---|
| **CRIT 0.1b** Manage Information | compile | `domain_decision_log.md` (D-01…D-08) + `target_schema.md` are precisely *"how conflicting or incomplete information was handled"* |
| **CRIT 0.3a** Contextual Factors | compile | Legal / accessibility / environmental / societal are thin — same root gap as CSMS 7.1 |
| **INFO 0.3a** Resource Value | **write, ≈1–2 d** | Both annotated bibliographies cover ~1 of the 5 required axes (*currency*) and **literature only**. The brief also counts APIs, libraries, repos, datasets and AI-generated content — so Gemini, Claude, FastAPI, SQLAlchemy, client domain knowledge and AI-assisted code each need accuracy / authority / bias / currency / relevance |
| **CSMS 1.1** Theoretical Analysis | **partial, ≈1 d + A8** | A4 `04_computational_methods.md` is solid. But `engineering/acra_srs_v2.1.md` references **15 diagrams at `docs/diagrams/images/*.png` that do not exist** in either repo and were never committed. Resource/complexity analysis comes from **A8-6 + A8-7** |
| **CSMS 2.1** Software Design | compile + **labelling pass, ≈0.5 d** | Brief requires every model element be labelled *Fully implemented / Partially / Simulated / Mocked / Externally provided / Proposed / Future*. With the ledger stubbed and worksheets UI-less, this pass is load-bearing — and it is what makes §5's deferral defensible |
| **CSMS 2.2** System Testing | **= A8** | Have the tests; missing variable-relationship analysis, baseline comparison, V&V traceability, defect→correction→retest records |
| **CSMS 7.1** Quality of Life | **write from scratch, ≈1–2 d** | A grep of all `acra_docs` for *quality of life · societal · labor displacement · sustainability · digital exclusion · surveillance* hits only the bibliography and the brief itself. A2 §7.2 is ethics-as-risk-mitigation, which is a different thing |

### 9.3 Additional effort beyond A8 + A10

**≈5–7 days:** INFO 0.3a resource evaluation (1–2) · CSMS 7.1 impact analysis (1–2) · regenerate the
15 SRS diagrams (~1) · implemented/partial/mocked labelling pass (~0.5) · final synthesis report and
archive assembly (1–2).

### 9.4 Raw material for CSMS 7.1 that already exists but is unwritten

The hole is the writeup, not the substance:

- **Bilingual EN/ES UI** (`next-intl`, `messages/`) — accessibility and inclusion on a
  Spanish-speaking floor.
- **Audit trail on every data-modifying operation** — cuts both ways: accountability *and* worker
  surveillance. Name both.
- **Digitizing a paper process the operators currently own** — labor effects, autonomy, training
  burden, and what happens when the system is down.
- **LLM extraction path** — energy and per-call cost, plus dependency on two US-hosted providers for
  a single Spanish facility (autonomy, data residency, provider deprecation risk).
- **Who is disadvantaged** — the brief explicitly asks. Answer it about operators and about the
  fallback-to-paper path, not only about the client's efficiency gains.
