# Plan — A8 / A10 Readiness

**Status:** draft for review
**Written against:** `master` @ `7649a6e` (`ticket-21: T21 — End-to-End Tests (Playwright) (#33)`)
**Date:** 2026-07-30

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
- `plans/plan_ticket_35.md:234` says the shipping-privilege grants landed in migration `012`; they
  landed in `013_shipping_privileges.py`.
- `backend/alembic.ini:6` carries a stale `sqlalchemy.url` on port **5432**. It is always
  overridden, but it reads as documentation and contradicts the documented 5433.
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
| A8-1 | Parameterized seed — `seed_fake_data.py --scale N` | **ACR-41** | ✅ done — `--scale/--deliveries/--work-orders/--materials/--json`, scale-1 proven bit-identical | `ticket-41/parameterized-seed` |
| A8-2 | Benchmark harness — run metadata, p50/p95/p99, machine-readable output | **ACR-43** | ✅ done — `app/core/benchmark.py`; first consumer `api_latency_bench.py`; `validation-run.sh` stage 6c | `ticket-43/bench-harness-request-timing` (#36) |
| A8-3 | Request-timing middleware + structured request logs | **ACR-43** | ✅ done — `app/core/observability.py`, folded into A8-2 | `ticket-43/bench-harness-request-timing` (#36) |
| A8-4 | OCR accuracy + provider comparison bench | **ACR-36** | 🔄 in progress — `ticket-36/ocr-accuracy-bench`, plan at `plans/plan_ticket_36.md` | — |
| A8-5 | Comparative concurrency study (3-arm ablation) | **ACR-44** | 🔄 in progress — `ticket-44/comparative-concurrency-study`, plan at `plans/plan_ticket_44.md` | — |
| A8-6 | Aggregation benchmark at volume (RSK-04) | **ACR-45** | ⬜ — ticket written; `inventory_lots` carries **no index at all**, so RSK-04's own mitigation is half-applied | — |
| A8-7 | Subsystem diagram marking measurement points | — | ⬜ | — |
| A10-1 | Dockerfiles for backend + frontend; whole-stack compose | **ACR-42** | 🔄 in progress | — |
| A10-2 | OCR offline/mock mode + committed sample fixtures | — | ⬜ | — |
| A10-3 | CI: Playwright job, all 20 Jest files, frontend coverage gate | — | ⬜ blocked on §6 #3 + wants A10-1 first | — |
| A10-4 | Lockfile + Node/Python version reconciliation, pin AI SDKs | **ACR-42** | 🔄 in progress — folded into A10-1 | — |
| A10-5 | Privilege-parity test (seed vs migrations); fix/delete `create_admin.py` | (ACR-40 adjacent) | ⬜ | — |
| A10-6 | LICENSE + data-provenance doc | — | ⬜ | — |
| A10-7 | README troubleshooting, expected-output transcript, runbook | — | ⬜ | — |
| A10-8 | Repo hygiene (untrack `backend/.coverage`, stray PNGs, `plans/` policy) | — | ⬜ | — |
| §7 | Doc corrections (ACR-31 description, plan_ticket_35:234, alembic.ini:6, `acra_docs` rename) | — | ⬜ | — |

**A10-4 is folded into A10-1 under one ticket** (ACR-42): a correct Dockerfile cannot be written
before the Node and Python versions are settled, and §4 already sequences A10-4 → A10-1. Splitting
them would mean writing the images twice.

**A8-3 is folded into A8-2 under one ticket** (ACR-43): both are §2.3 items with **no dependencies**,
both are the same missing thing — §1's "no measurement infrastructure of any kind" — and the timing
middleware is the in-process source the harness reports on. §4 already runs them into the same
convergence point. Splitting them would mean defining the run-metadata and percentile conventions
twice.

### 8.2 Completed

When an item lands, append a row here rather than only flipping §8.1 — the evidence column is what
makes the writeup citable.

| # | Item | Date | Commit / PR | Evidence produced |
|---|---|---|---|---|
| **A8-1** | Parameterized seed (ACR-41) | 2026-07-30 | `ticket-41/parameterized-seed` | See `plans/plan_ticket_41.md` §9. **Scale-1 fixture proven bit-identical** across all 14 seeded tables (per-table SHA-256 of full ordered content, captured before/after on freshly migrated databases) — the contract the 83 Playwright specs depend on. **Volume/timing:** scale 50 = 1 200 deliveries / 3 700 lots / 400 work orders in **8.9 s**; scale 200 = 14 800 lots in **31.8 s**; ~linear, so the planned bulk-insert follow-up is unnecessary. **Idempotence:** re-seeding creates 0 rows; raising the scale adds exactly one unit. **Supply/demand headroom** 176× at scale 1 vs 165× at scale 50 — the ratio-preservation claim measured, not assumed. 40 pure tests + 6 guarded live-DB tests. |
| **A8-2 + A8-3** | Benchmark harness & request-timing middleware (ACR-43) | 2026-07-31 | `ticket-43/bench-harness-request-timing` (#36) | `app/core/benchmark.py` — nearest-rank p50/p95/p99 pinned against a known vector, `RunMetadata` capturing git SHA/tag/dirty + host + redacted DSN + exact command, JSON+text artifact pair under `validation-evidence/`. `app/core/observability.py` — per-request structured logs (status, route, duration, request id). First consumer `scripts/validation/api_latency_bench.py` over 5 read endpoints; wired as `validation-run.sh` stage 6c. **Credentials never reach an artifact** — asserted end to end on both files, not assumed. |
| — | — | — | — | — |

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
