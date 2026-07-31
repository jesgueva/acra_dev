# Plan — ACR-36 · OCR accuracy gate + provider comparison bench

**Ticket:** [ACR-36](https://linear.app/chronos-laboral/issue/ACR-36/ocr-accuracy-gate-vs-real-client-bol-corpus) — rescoped to **A8-4** of [`plan_a8_a10_readiness.md`](plan_a8_a10_readiness.md) §2.3
**Branch:** `ticket-36/ocr-accuracy-bench` (cut from `origin/master`)
**Blocked by:** ACR-8 (T08 OCR Service) — **Done** ✅
**Refs:** F3 · SC-2 · KI-09 · ISS-05 · RSK-03 · TC-03
**Rubric hooks:** A8 Testing/Benchmarking/**Comparative** 20 · Technical Reasoning 20 · Evidence Packaging 20

**Decided before planning (do not re-open):** corpus is **synthetic only** — redistributable, in-repo,
CI-safe. Plan §6 open decision #2 is settled.

---

## 1. Current state

### 1.1 The claim with no number behind it

SC-2 promises *"field-level line-item accuracy ≥ the v6 baseline."* **No such number exists in the
repo.** Verified on `origin/master`:

| Artifact | State |
|---|---|
| `backend/app/services/ocr_service.py` | 226 lines, two-tier Gemini→Claude pipeline, working |
| `backend/tests/test_ocr.py` | 10 tests, **100% mocked**, **zero accuracy assertions** |
| `scripts/validation/ocr_roundtrip.py` | 1 synthetic doc, **prints without asserting** |
| `frontend/e2e/ticket-21-ocr.spec.ts` | endpoint stubbed with `Buffer.from("not-a-real-image…")` |
| BOL corpus | none — `git ls-tree` finds no `*.pdf` / `*bol*` fixture anywhere |
| Accuracy baseline | none |

### 1.2 Four defects found while reading

**D1 — `confidence` is a fill rate, not accuracy.** `ocr_service.py:104-105`:

```python
filled = sum(1 for v in [supplier, carrier, bol_reference, delivery_date] if v)
confidence = round(filled / 4.0, 2)
```

Four *wrong* header values score `1.0`. This is the number the 422 gate
(`deliveries.py:42`) and the Gemini→Claude fallback trigger (`ocr_service.py:209`) both hinge on.

**D2 — `provider` is computed and thrown away.** `_build_response(data, provider)` at
`ocr_service.py:99` takes the parameter and never uses it. `OCRResponse`
(`schemas/delivery.py:81-87`) has no provider field, so **a caller cannot tell whether Gemini
answered or the Claude fallback did** — which is exactly what a provider comparison needs.

**D3 — the scorer aligns line items positionally.** `ocr_roundtrip.py:125-126`:

```python
for gi, (name, pal, upp, qty) in enumerate(GROUND_TRUTH["items"]):
    match = got_items[gi] if gi < len(got_items) else {}
```

One dropped or reordered row shifts every subsequent comparison and scores the whole table wrong.
The readiness plan calls this out by name.

**D4 — `test_ocr.py` encodes an obsolete schema.** Lines 36 and 151 construct
`OCRItemResult(material_type=…, lot_batch_number=…)`, but the real fields are
`item_name / description / quantity / pallets / units_per_pallet`
(`schemas/delivery.py:73-78`). Pydantic v2 silently drops the unknown kwargs, so the tests pass
while asserting nothing about item identity. The suite is green *because* it is checking the wrong
fields.

### 1.3 What to extend, not rebuild

- `scripts/validation-run.sh:95-103` — stage 6b already runs the round-trip behind an API-key guard
  and writes a provenance header (`hdr()` at :43, git SHA + tag + host + exact command).
- `backend/tests/integration/test_reservation_availability.py:38-40` — the closest existing pattern
  for an **asserted** numeric gate (`LATENCY_BUDGET_MS = 200.0`, p95 over 20 samples).
- `scripts/validation/ocr_roundtrip.py:40-85` — the Pillow BOL renderer. Reusable as the "gridded"
  layout; the other five layouts are new.

### 1.4 Facts that shrink this ticket

- **`Pillow==11.0.0` is already in `requirements.txt`** (line 13) and fuzzy alignment needs only
  stdlib `difflib.SequenceMatcher` → **zero new dependencies**, so `requirements.txt` is not touched
  at all and the ACR-42 conflict surface is **nil** (better than the one-line budget).
- **No migration.** No schema change; Alembic stays at head `014`.
- **`confidence` is never rendered.** It appears in the frontend only as a TS field
  (`OCRUploader.tsx:22`) and two test fixtures. Adding sibling fields is near-zero UI risk.
- `validation-evidence/` is **git-ignored** (`.gitignore:31-32`), so bench *runs* are not committed —
  the **baseline** must live in a tracked file instead.

---

## 2. Change list

### CREATE — bench package (`backend/scripts/ocr_bench/`)

Implicit namespace package; **no `backend/scripts/__init__.py`** (adding one risks how
`seed_fake_data.py` is invoked — and that file belongs to ACR-41).

| File | Purpose |
|---|---|
| `__init__.py` | Package marker for `from scripts.ocr_bench import …` under `PYTHONPATH=backend` |
| `corpus.py` | Deterministic Pillow generator for the 6 layouts + their ground truth |
| `ground_truth.py` | The labelled dataset: one `BolSpec` per document, single source of truth |
| `scoring.py` | Field-level scorer — header exact/normalized match + **fuzzy line-item alignment** |
| `run_bench.py` | Opt-in CLI: renders corpus → calls provider(s) → scores → writes JSON + markdown |

### CREATE — fixtures & tests

| File | Purpose |
|---|---|
| `backend/tests/fixtures/ocr/baseline.json` | **Tracked** recorded baseline the gate compares against |
| `backend/tests/fixtures/ocr/sample_bol_gridded.png` | One committed image so the OCR path is runnable offline (A10-2) |
| `backend/tests/test_ocr_scoring.py` | Unit tests for the scorer + corpus. Pure functions, no network |
| `backend/tests/integration/test_ocr_accuracy.py` | The **asserted** no-regression gate, opt-in via env |
| `frontend/e2e/ticket-36.spec.ts` | Receiving OCR flow still works with the enriched response shape |

### MODIFY

| File | Change |
|---|---|
| `backend/app/schemas/delivery.py` | `OCRResponse`: add `provider: Optional[str]`, add `header_fill_rate: float`; docstring stating plainly that `confidence` is a fill rate, not accuracy (**D1**) |
| `backend/app/services/ocr_service.py` | `_build_response` populates `provider` (**D2**) and `header_fill_rate`; pass `"gemini"` / `"claude"` through from the two extractors |
| `backend/tests/test_ocr.py` | Fix the obsolete `material_type` / `lot_batch_number` kwargs (**D4**); assert `provider` on the fallback tests |
| `scripts/validation/ocr_roundtrip.py` | Use `scoring.py` instead of positional matching (**D3**); **`sys.exit(1)` on failure** |
| `scripts/validation-run.sh` | New stage **6c** — provider comparison bench (fold in, do not renumber 1–7) |
| `frontend/src/components/receiving/OCRUploader.tsx` | Add `provider?` / `headerFillRate?` to the response interface |
| `frontend/src/components/receiving/__tests__/Receiving.test.tsx` | Keep fixtures aligned with the new shape |
| `plans/plan_a8_a10_readiness.md` | **§8.1** flip A8-4 to 🔄 then ✅ with ticket **ACR-36**; **§8.2** append the evidence row |
| `KNOWN_ISSUES.md` | Retire/annotate KI-09; record the `confidence` semantics correction |

---

## 3. Design

### 3.1 Corpus — generator + ground truth, not committed binaries

`CONTRIBUTING.md:78` puts *"large binaries, datasets"* out of the repo. So the corpus ships as a
**deterministic generator plus labels**, which is strictly better for the A8 rubric ("record methods
so the run can be repeated") and keeps the repo small:

- `ground_truth.py` holds six `BolSpec` records — the labels are the committed artifact.
- `corpus.py` renders them with a **fixed seed**, byte-reproducible on any host, into a
  git-ignored output dir.
- Exactly **one** rendered PNG is committed (`sample_bol_gridded.png`, ~40 KB) so the receiving flow
  and A10-2's offline mode have something to upload without running the generator.

Six layouts, each targeting a documented failure mode:

| Layout | What it probes |
|---|---|
| `gridded` | Baseline — ruled table, clear columns (today's `ocr_roundtrip.py` doc) |
| `borderless_cramped` | ISS-05 / KI-09: the layout sensitivity the ticket was filed for |
| `rotated` | ~4° skew from a phone photo of a paper BOL |
| `multipage` | 2-page PDF — line items split across a page break |
| `spanish` | `Proveedor / Transportista / Palets / Ud. por palet`, **European thousands** (`17.122`) — exercises rules 3 & 4 of `_OCR_EXTRACTION_INSTRUCTIONS` (`ocr_service.py:64-73`) |
| `poor_scan` | Gaussian noise + low contrast + JPEG artifacts |

`spanish` also covers the `TRANSFERENCIA → supplier = "Internal"` rule (`ocr_service.py:59-61`),
which nothing tests today.

### 3.2 Scorer — fuzzy alignment (fixes D3)

```
score(expected: BolSpec, actual: OCRResponse) -> BolScore
```

- **Header fields** — normalize (casefold, strip punctuation/accents, collapse whitespace); dates
  parsed to `date` before comparison so `2026-06-23` == `23/06/2026`. Per-field `bool`.
- **Line items** — greedy best-match on `difflib.SequenceMatcher` ratio over normalized
  `item_name`, threshold **0.75**, each extracted row consumable once. Unmatched expected rows are
  *misses*, unmatched extracted rows are *spurious*. Numeric fields compared only within a matched
  pair, exact for `pallets` / `units_per_pallet`, `abs(a-b) <= 0.01` for `quantity`.
- Reports **precision / recall / F1** on line items plus per-field header accuracy — not one blended
  number, because the ticket's whole point is that *line items* are the layout-sensitive part while
  *headers* are robust.

Zero new dependencies: `difflib` and `unicodedata` are stdlib.

### 3.3 Provider comparison

`run_bench.py --provider {gemini,claude,both} --repeat N --out DIR`

Calls `_extract_with_gemini` / `_extract_with_claude` **directly**, bypassing
`process_image_bytes`, so the fallback chain cannot mask which model actually answered. Per
document × provider × repeat it records latency; output is:

- `ocr-bench.json` — machine-readable: run metadata (git SHA, host, OS, python, **model IDs**,
  params, UTC timestamp), per-document per-provider scores, latency p50/p95/p99.
- `ocr-bench.md` — the head-to-head table for the writeup.

Both land under `validation-evidence/ocr-bench/` (git-ignored), with the same provenance header
shape `validation-run.sh:43-50` already uses.

### 3.4 The asserted gate (fixes the "prints without asserting" defect)

`backend/tests/integration/test_ocr_accuracy.py`:

- **Skips** unless `OCR_BENCH_LIVE=1` **and** the relevant API key is set — same guard idiom as the
  other integration tests. CI stays offline and key-free.
- Loads `backend/tests/fixtures/ocr/baseline.json` and asserts measured ≥ baseline − tolerance
  (`0.05` absolute, to absorb model nondeterminism) on header accuracy and line-item F1.
- A **negative control**: a deliberately corrupted extraction must score *below* the gate. Without
  it the gate cannot distinguish "correct" from "always passes" — the same reasoning as
  `test_worksheet_close_concurrency.py`'s unguarded-shape control.

The baseline in `baseline.json` is **measured on this branch and committed**, with the run metadata
that produced it recorded alongside it.

### 3.5 `confidence` — supplement, don't silently redefine (fixes D1/D2)

`confidence` keeps its wire meaning and stays the fallback/422 trigger (changing it would alter
error behaviour, which is out of scope here). Alongside it:

- `header_fill_rate: float` — the same number, **correctly named**.
- `provider: Optional[str]` — `"gemini"` or `"claude"`, from the already-present-but-dead argument.
- A schema docstring saying in one line that `confidence` measures *presence*, not *correctness*,
  and pointing at the bench for real accuracy.

This is the "replace or supplement… and say so in the writeup" the readiness plan asks for, at the
lowest possible blast radius.

---

## 4. Test plan

**Backend — offline, no keys, runs in CI**

| Case | Assertion |
|---|---|
| Corpus determinism | Two renders of the same spec are byte-identical |
| Corpus coverage | All 6 layouts render; ground truth non-empty for each |
| Header scoring | Exact, case/punctuation-normalized, and date-format-variant matches |
| Header scoring negative | Wrong value scores 0 — the D1 defect, asserted |
| Item alignment | Reordered rows still match; **dropped row shifts nothing** (the D3 regression) |
| Item alignment | Spurious extra row counts against precision, not recall |
| Item alignment | Near-miss names above/below the 0.75 threshold behave as specified |
| Numeric tolerance | `quantity` within 0.01 passes; `pallets` off-by-one fails |
| `provider` propagation | Gemini path → `"gemini"`; forced fallback → `"claude"` |
| `header_fill_rate` | Equals the old `confidence` computation on the same input |
| Baseline gate logic | Below-baseline scores fail the comparison (tested on synthetic scores, no network) |
| RBAC | `POST /deliveries/ocr` without `deliveries.create` → **403** (3-query pattern via `tests/conftest.py`) |
| Validation | Oversize → 422, unsupported type → 422 (existing, keep green) |

**Backend — opt-in live** (`OCR_BENCH_LIVE=1`): the gate itself + the negative control.

**Frontend:** `Receiving.test.tsx` fixtures updated for the enriched shape; render unaffected.

**E2E:** `frontend/e2e/ticket-36.spec.ts` — upload on the receiving page with a stubbed OCR
response carrying `provider` + `header_fill_rate`, assert the review form still populates and
submits. Run against `npm run build && npm run start`, **not `next dev`** (KI-02).

**Gate:** pytest ≥85% on `app.*`, `npx jest`, `npm run lint`, `npm run build`,
`./scripts/smoke-test.sh`, the Playwright spec.

---

## 5. Live verification

1. `POST /api/v1/deliveries/ocr` with each of the 6 layouts against the real pipeline; confirm
   `provider` reports truthfully and the Spanish thousands-separator doc returns `17122`, not `17.122`.
2. Force the fallback (bad `GEMINI_API_KEY`) → response reports `provider: "claude"`.
3. Browser: receiving page → upload `sample_bol_gridded.png` → review form populates → submit;
   both locales (`/en/`, `/es/`); console and network clean.
4. Permission check: a user without `deliveries.create` is **blocked**, not merely hidden from.
5. `./scripts/validation-run.sh` end to end — stage 6c produces `ocr-bench.json` + `ocr-bench.md`.

---

## 6. Risks / open questions

**Non-blocking — proceeding as stated:**

1. **Corpus as generator vs committed PNGs.** Going generator + one committed sample per
   `CONTRIBUTING.md:78`. Switching to all-six-committed is a one-line change if preferred.
2. **Model nondeterminism.** Same document, same model, different runs → different extractions. Hence
   the 0.05 tolerance and `--repeat N`. If variance exceeds tolerance, the honest fix is to widen the
   band and *report the variance* rather than tighten until green.
3. **Synthetic ≠ real.** Synthetic BOLs are cleaner than a real phone photo, so the measured number
   is an **upper bound**. This must be stated in the A8 writeup, not buried — A8 rewards naming
   "limitations of the current evidence itself."
4. **Live bench costs money** (6 docs × 2 providers × N repeats). Opt-in only; never in CI.

**Blocking:** none.

**Collision surface with the parallel worktrees:** `requirements.txt` untouched (zero conflict with
ACR-42); `seed_fake_data.py` untouched (zero conflict with ACR-41). Shared file is
`plans/plan_a8_a10_readiness.md` §8 — a different row each, so a trivial merge.

---

## 7. Build order

1. `ground_truth.py` + `corpus.py` — 6 layouts, deterministic; tests for determinism and coverage.
2. `scoring.py` — fuzzy alignment; the full scorer test table above, **including the D3 regression**.
3. Schema + service: `provider`, `header_fill_rate`, docstring; fix `test_ocr.py`'s stale kwargs (D4).
4. `run_bench.py` — CLI, run metadata, JSON + markdown output.
5. Measure the real baseline; commit `baseline.json` with its provenance.
6. `test_ocr_accuracy.py` — asserted gate + negative control.
7. Rewire `ocr_roundtrip.py` onto the scorer and make it `sys.exit(1)`; add `validation-run.sh` 6c.
8. Frontend interface + fixtures; `ticket-36.spec.ts`.
9. Update `plan_a8_a10_readiness.md` §8.1/§8.2 and `KNOWN_ISSUES.md`.
10. Full gate, then draft PR.
