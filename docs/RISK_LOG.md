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
| RSK-01 | Concurrency-safe production-worksheet close has a subtle lost-update path under parallel closes on the same stock row. | High | Med | **Mitigated (ACR-30).** Protocol decided and recorded as ADR-02 in `architecture.md`: parent row `FOR UPDATE`, then one conditional `UPDATE … WHERE version = :expected` (rowcount → 409) before any stock moves, then lots locked in `id ASC` order. TC-02 (`tests/integration/test_worksheet_close_concurrency.py`) proves it against real Postgres at 8×5 and 16×20 closers, with a negative control asserting the unguarded close *does* lose updates. **Residual:** `FOR UPDATE` over zero rows locks nothing — benign for lots, not for the ledger's `(item, state)` aggregate; ACR-31 needs an advisory lock or a balance anchor row (see ADR-02 carry-forward). | Lead Dev | Mitigating | 2026-06-16 | 2026-07-23 |
| RSK-02 | Migration from the lot-centric model to the append-only ledger loses or garbles existing stock on backfill. | High | Med | Reversible-by-design migration; round-trip + on-hand parity test on a realistic fixture before cutover. | Lead Dev | Open | 2026-06-16 | 2026-06-16 |
| RSK-03 | AI receiving-document extractor regresses below the established OCR accuracy baseline, or the hosted provider is slow/unstable. | Med | Med | Schema-constrained output + provider fallback chain (primary → fallback); no-regression accuracy gate and a latency gate in the test plan; manual entry always available. **Validated live (2026-06-23):** a real Gemini 2.5 Flash round-trip extracted all header fields at confidence 1.0; line-item extraction proved layout-sensitive (1/3 rows on a cramped table, 3/3 on a gridded one — ISS-05/KI-09). | Lead Dev | Mitigating | 2026-06-16 | 2026-06-23 |
| RSK-04 | Ledger on-hand/reserved/available aggregation is slow at data volume. | Med | Low | Index by `(item, state)`; keep a periodic-snapshot fallback in reserve if reads degrade. | Lead Dev | Monitoring | 2026-06-16 | 2026-06-16 |
| RSK-05 | Open domain questions shift the schema late, after dependent surfaces are built. | Med | Med | Mark schema elements that depend on open items as conditional; lock the open items at sprint kickoff before building dependents. | Lead Dev | Open | 2026-06-16 | 2026-06-16 |
| RSK-06 | Scope pressure across the remaining operator surfaces threatens the MVP bar. | Med | Med | Pre-agreed descope order (lowest-priority surfaces first); the MVP acceptance bar holds without them. | Lead Dev | Monitoring | 2026-06-16 | 2026-06-16 |
| RSK-07 | Single-developer project — bus factor: knowledge and momentum concentrate in one person. | Med | Med | Keep `CLAUDE.md`, `README.md`, and these logs current; small reviewable commits; tagged baselines so any point is reproducible from docs alone. | Lead Dev | Mitigating | 2026-06-16 | 2026-06-16 |
| RSK-08 | Secrets (API keys, JWT secret) leak via a committed `.env`. | High | Low | `.env` is git-ignored; only `.env.example` templates are tracked; rotate any key ever shared; inject secrets in CI/deploy rather than committing them. | Lead Dev | Mitigating | 2026-06-16 | 2026-06-16 |
| RSK-09 | Reproducibility drift — a clean-environment install fails because a transitive dependency is unpinned (as happened with `greenlet`). | Med | Low | Pin direct + load-bearing transitive deps; the smoke test runs a clean install path; re-verify on a fresh machine before each tagged baseline. | Lead Dev | Resolved | 2026-06-16 | 2026-06-16 |

## Issues (active)

| ID | Description | Severity | Mitigation / action | Owner | Status | Opened | Updated |
|---|---|---|---|---|---|---|---|
| ISS-01 | Schema integration tests default to port 5432 and fail against the Compose Postgres (5433) without `DATABASE_URL` set. | Low | Documented in `KNOWN_ISSUES.md` (KI-01); smoke test and CI export `DATABASE_URL`. Consider defaulting to 5433. | Lead Dev | Monitoring | 2026-06-16 | 2026-06-16 |
| ISS-02 | Turbopack dev server can panic on first route compile, blanking the page until restart. | Low | Documented (KI-02); production build unaffected; use `next start` for stable demos. | Lead Dev | Monitoring | 2026-06-16 | 2026-06-16 |
| ISS-03 | `POST /api/v1/deliveries` creates inventory lots without a `lot_number`, so `GET /api/v1/inventory/trace/{lot_number}` cannot resolve API-received lots (storage-layer provenance via `source_delivery_item_id` is intact). | Med | Assign a lot number on receipt in `delivery_service.create_delivery`; documented as KI-07. | Lead Dev | Open | 2026-06-23 | 2026-06-23 |
| ISS-04 | `shipping.*` privileges are seeded to no role (migration `002`), so the implemented shipment endpoints return 403 for all users — the shipping backend is RBAC-orphaned. | Med | Add `shipping.create`/`shipping.view` to the role-privilege seed; documented as KI-08. | Lead Dev | Open | 2026-06-23 | 2026-06-23 |
| ISS-06 | Three divergent stock-drawdown implementations. TC-02's negative control (ACR-30) demonstrates in CI that the unguarded read-modify-write shape loses updates — and that is the shape `inventory_service.adjust_quantity` and `shipment_service.create_shipment` still use, while `allocation_service` uses the SERIALIZABLE approach ADR-02 rejects. Only the worksheet close is guarded. | Med | Apply the ADR-02 protocol to the remaining drawdown paths, or converge them on one helper when the ledger lands (ACR-31). Out of scope for the ACR-30 spike, which deliberately changed no existing service. | Lead Dev | Open | 2026-07-23 | 2026-07-23 |
| ISS-05 | OCR line-item extraction is layout-sensitive (1/3 rows on a cramped table, 3/3 on a gridded one); header-field extraction is robust. | Low | Validate against real client BOLs under the RSK-03 accuracy gate; documented as KI-09. | Lead Dev | Monitoring | 2026-06-23 | 2026-06-23 |

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
