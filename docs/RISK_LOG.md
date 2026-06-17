# Risk & Issue Log

Actively tracked engineering risks and issues for ACRA MES. Each entry has a stable identifier,
a severity and likelihood, a concrete mitigation action, an owner, and a status. Design-level
risks are carried forward from the Phase 2 design review (referenced as `R-0x`) and translated
here into live, tracked items; operational/process risks discovered during the Sprint I baseline
are added alongside them.

**Severity:** High / Med / Low — impact if it occurs.
**Likelihood:** High / Med / Low — chance it occurs without further action.
**Status:** Open · Mitigating · Monitoring · Resolved.

Last reviewed: **2026-06-16** · Owner role key: *Lead Dev* (single-developer applied project).

## Risks

| ID | Description | Severity | Likelihood | Mitigation action | Owner | Status | Opened | Updated |
|---|---|---|---|---|---|---|---|---|
| RSK-01 | Concurrency-safe production-worksheet close has a subtle lost-update path under parallel closes on the same stock row. | High | Med | De-risk **first** in Sprint II with a focused spike; add an N-parallel-close concurrency test (optimistic version + narrow row lock) before building dependent surfaces. | Lead Dev | Open | 2026-06-16 | 2026-06-16 |
| RSK-02 | Migration from the lot-centric model to the append-only ledger loses or garbles existing stock on backfill. | High | Med | Reversible-by-design migration; round-trip + on-hand parity test on a realistic fixture before cutover. | Lead Dev | Open | 2026-06-16 | 2026-06-16 |
| RSK-03 | AI receiving-document extractor regresses below the established OCR accuracy baseline, or the hosted provider is slow/unstable. | Med | Med | Schema-constrained output + provider fallback chain (primary → fallback); no-regression accuracy gate and a latency gate in the test plan; manual entry always available. | Lead Dev | Mitigating | 2026-06-16 | 2026-06-16 |
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

## Change log for this register
- **2026-06-16** — Register created at the Sprint I baseline. Seeded design risks RSK-01…RSK-06
  from the Phase 2 design review; added operational risks RSK-07…RSK-09 and issues ISS-01…ISS-02
  found during baseline verification. RSK-09 resolved within the sprint (greenlet pinned).
