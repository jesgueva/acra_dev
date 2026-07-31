# Risk & Issue Log

Actively tracked engineering risks and issues for ACRA MES. Each entry has a stable identifier,
a severity and likelihood, a concrete mitigation action, an owner, and a status. Design-level
risks are carried forward from the Phase 2 design review (referenced as `R-0x`) and translated
here into live, tracked items; operational/process risks discovered during the Sprint I baseline
are added alongside them.

**Severity:** High / Med / Low — impact if it occurs.
**Likelihood:** High / Med / Low — chance it occurs without further action.
**Status:** Open · Mitigating · Monitoring · Resolved.

Last reviewed: **2026-06-23** (Hard Stop 3 validation review) · Owner role key: *Lead Dev* (single-developer applied project).

## Risks

| ID | Description | Severity | Likelihood | Mitigation action | Owner | Status | Opened | Updated |
|---|---|---|---|---|---|---|---|---|
| RSK-01 | Concurrency-safe production-worksheet close has a subtle lost-update path under parallel closes on the same stock row. | High | Med | De-risk **first** in Sprint II with a focused spike; add an N-parallel-close concurrency test (optimistic version + narrow row lock) before building dependent surfaces. **Spiked and proven (ACR-30, 2026-07-23):** optimistic version guard + ascending-id row locks under Read Committed hold across 8 parallel closes × 5 repeated rounds — one winner, correct on-hand, one movement, every run (TC-02, `backend/tests/integration/test_worksheet_close_concurrency.py`, mutation-verified: deleting either guard turns it red). Stays *Mitigating*, not Resolved — the protocol is proven against `inventory_lots`; ACR-31 must carry it to the ledger, where the zero-row `FOR UPDATE` gap noted in ADR-02 applies. | Lead Dev | Mitigating | 2026-06-16 | 2026-07-23 |
| RSK-02 | Migration from the lot-centric model to the append-only ledger loses or garbles existing stock on backfill. | High | Med | Reversible-by-design migration; round-trip + on-hand parity test on a realistic fixture before cutover. | Lead Dev | Open | 2026-06-16 | 2026-06-16 |
| RSK-03 | AI receiving-document extractor regresses below the established OCR accuracy baseline, or the hosted provider is slow/unstable. | Med | Med | Schema-constrained output + provider fallback chain (primary → fallback); no-regression accuracy gate and a latency gate in the test plan; manual entry always available. **Validated live (2026-06-23):** a real Gemini 2.5 Flash round-trip extracted all header fields at confidence 1.0; line-item extraction proved layout-sensitive (1/3 rows on a cramped table, 3/3 on a gridded one — ISS-05/KI-09). | Lead Dev | Mitigating | 2026-06-16 | 2026-06-23 |
| RSK-04 | Ledger on-hand/reserved/available aggregation is slow at data volume. | Med | Low | Index by `(item, state)`; keep a periodic-snapshot fallback in reserve if reads degrade. **Measured (ACR-45 / A8-6, 2026-07-31):** the mitigation was only ever half-applied — `stock_reservations` was indexed in revision 010, `inventory_lots` had no index beyond its primary key, so the `_on_hand` half of every `availability` call sequentially scanned the table. Migration `015` adds `(product_id, status) INCLUDE (quantity_on_hand)`. Server-side execution time for that aggregate, via real service calls at 1k/10k/50k/200k bench lots (over ~14 800 ambient seeded lots): **14.134 ms → 0.029 ms at 200 000 lots (487×)**, plan `Seq Scan` → `Index Only Scan` at every volume. The decisive shape: unindexed cost grows with the table (2.9 → 2.6 → 3.9 → 14.1 ms) while indexed cost stays **flat and sub-0.04 ms** (0.034 → 0.038 → 0.009 → 0.029 ms). **The periodic-snapshot fallback is retired** — a flat sub-0.04 ms aggregate out to 200k lots has no read-degradation curve to defend against, and a snapshot would add a staleness window plus an invalidation path for no measured gain. Evidence: `validation-evidence/aggregation-bench-summary.json` + `aggregation-explain-plans.txt`; guarded by `tests/integration/test_aggregation_at_volume.py`, whose negative control drops the index inside a rolled-back transaction and asserts the plan degrades. **The other three measured paths, reported rather than hidden:** `list_alerts` groups over the whole table with no `WHERE` and **stays a `Seq Scan` at every volume** (45.6 → 29.7 ms at 200k — the covering index shaves heap reads off the `GROUP BY` but cannot change the plan); `list_inventory` was already index-only via the primary key (~1.0×); `export_csv` is unpaginated and is carried separately as RSK-10. | Lead Dev | **Resolved** | 2026-06-16 | 2026-07-31 |
| RSK-05 | Open domain questions shift the schema late, after dependent surfaces are built. | Med | Med | Mark schema elements that depend on open items as conditional; lock the open items at sprint kickoff before building dependents. | Lead Dev | Open | 2026-06-16 | 2026-06-16 |
| RSK-06 | Scope pressure across the remaining operator surfaces threatens the MVP bar. | Med | Med | Pre-agreed descope order (lowest-priority surfaces first); the MVP acceptance bar holds without them. | Lead Dev | Monitoring | 2026-06-16 | 2026-06-16 |
| RSK-07 | Single-developer project — bus factor: knowledge and momentum concentrate in one person. | Med | Med | Keep `CLAUDE.md`, `README.md`, and these logs current; small reviewable commits; tagged baselines so any point is reproducible from docs alone. | Lead Dev | Mitigating | 2026-06-16 | 2026-06-16 |
| RSK-08 | Secrets (API keys, JWT secret) leak via a committed `.env`. | High | Low | `.env` is git-ignored; only `.env.example` templates are tracked; rotate any key ever shared; inject secrets in CI/deploy rather than committing them. | Lead Dev | Mitigating | 2026-06-16 | 2026-06-16 |
| RSK-09 | Reproducibility drift — a clean-environment install fails because a transitive dependency is unpinned (as happened with `greenlet`). | Med | Low | Pin direct + load-bearing transitive deps; the smoke test runs a clean install path; re-verify on a fresh machine before each tagged baseline. | Lead Dev | Resolved | 2026-06-16 | 2026-06-16 |
| RSK-10 | `inventory_service.export_csv` fetches the whole `inventory_lots` table into memory with no `LIMIT` and no streaming, so latency and backend memory both grow linearly with the table. | Med | Med | Quantified by ACR-45 (A8-6, 2026-07-31): **1 507 ms p95 at 50 000 bench lots, 2 782 ms p95 at 200 000** — the slowest path measured in the system by an order of magnitude, and essentially unimproved by the aggregation index because its cost is materialising rows, not finding them. Deliberately not fixed in ACR-45, which is a measurement ticket. Options: paginate the export, stream it via `StreamingResponse`, or impose a hard row cap that errors explicitly. Endpoint `GET /api/v1/inventory/export` (`inventory.view`). | Lead Dev | Open | 2026-07-31 | 2026-07-31 |

## Issues (active)

| ID | Description | Severity | Mitigation / action | Owner | Status | Opened | Updated |
|---|---|---|---|---|---|---|---|
| ISS-01 | Schema integration tests default to port 5432 and fail against the Compose Postgres (5433) without `DATABASE_URL` set. | Low | Documented in `KNOWN_ISSUES.md` (KI-01); smoke test and CI export `DATABASE_URL`. Consider defaulting to 5433. | Lead Dev | Monitoring | 2026-06-16 | 2026-06-16 |
| ISS-02 | Turbopack dev server can panic on first route compile, blanking the page until restart. | Low | Documented (KI-02); production build unaffected; use `next start` for stable demos. | Lead Dev | Monitoring | 2026-06-16 | 2026-06-16 |
| ISS-03 | `POST /api/v1/deliveries` creates inventory lots without a `lot_number`, so `GET /api/v1/inventory/trace/{lot_number}` cannot resolve API-received lots (storage-layer provenance via `source_delivery_item_id` is intact). | Med | Assign a lot number on receipt in `delivery_service.create_delivery`; documented as KI-07. | Lead Dev | Open | 2026-06-23 | 2026-06-23 |
| ISS-04 | `shipping.*` privileges are seeded to no role (migration `002`), so the implemented shipment endpoints return 403 for all users — the shipping backend is RBAC-orphaned. | Med | Add `shipping.create`/`shipping.view` to the role-privilege seed; documented as KI-08. | Lead Dev | Open | 2026-06-23 | 2026-06-23 |
| ISS-05 | OCR line-item extraction is layout-sensitive (1/3 rows on a cramped table, 3/3 on a gridded one); header-field extraction is robust. | Low | Validate against real client BOLs under the RSK-03 accuracy gate; documented as KI-09. | Lead Dev | Monitoring | 2026-06-23 | 2026-06-23 |
| ISS-06 | Three divergent stock-drawdown implementations. ACR-30's negative control demonstrates in CI that the unguarded read-modify-write shape loses updates — and that is the shape `inventory_service.adjust_quantity` and `shipment_service.create_shipment` still use, while `allocation_service` uses the SERIALIZABLE approach ADR-02 rejects. Only the worksheet close is guarded. | Med | Apply the ADR-02 protocol to the remaining drawdown paths, or converge them on one helper when the ledger lands (ACR-31). | Lead Dev | Open | 2026-07-23 | 2026-07-23 |

## Change log for this register
- **2026-06-16** — Register created at the Sprint I baseline. Seeded design risks RSK-01…RSK-06
  from the Phase 2 design review; added operational risks RSK-07…RSK-09 and issues ISS-01…ISS-02
  found during baseline verification. RSK-09 resolved within the sprint (greenlet pinned).
- **2026-06-23** — Hard Stop 3 (Early Implementation Validation) review. Code unchanged at
  `v0.2.0-sprint1-baseline`. RSK-03 updated with live round-trip evidence (OCR validated; line-item
  extraction layout-sensitive). Added issues ISS-03 (received lots lack `lot_number`), ISS-04
  (shipping privileges unseeded), ISS-05 (OCR layout sensitivity), all surfaced by the validation
  run (`scripts/validation-run.sh`) and documented in `KNOWN_ISSUES.md` (KI-07…KI-09).
- **2026-07-23** — ACR-30 concurrency spike. RSK-01 Open → **Mitigating**: the close protocol is
  decided (ADR-02 in `architecture.md`) and proven by TC-02 against real Postgres. It stays
  Mitigating rather than Resolved because the guarantee is proven for the **lot-centric** model;
  the zero-row `FOR UPDATE` gap means the append-only ledger needs an advisory lock or balance
  anchor before ACR-31 can inherit it. The spike also fixed two contention-only defects in the
  close path (ORM attributes read after `rollback()` expired them, which surfaced as 500s).
- **2026-07-31** — ACR-45 / A8-6 aggregation benchmark. RSK-04 Monitoring → **Resolved**: its
  mitigation was only ever half-applied (`stock_reservations` indexed in revision 010,
  `inventory_lots` not indexed at all), and migration `015` closes that with
  `(product_id, status) INCLUDE (quantity_on_hand)` — 14.134 ms → 0.029 ms of server-side execution
  time at 200 000 lots, `Seq Scan` → `Index Only Scan`, with indexed cost flat across the whole
  volume sweep. **The periodic-snapshot fallback named in the original mitigation is retired**
  rather than left standing, since there is no measured degradation curve for it to defend against.
  New **RSK-10** opened for the finding the sweep turned up instead: `export_csv` is unpaginated and
  unstreamed, at 2 782 ms p95 over 200 000 lots.
