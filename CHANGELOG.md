# Changelog

All notable changes to ACRA MES are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Phase 2 realignment toward the append-only `StockMovement` ledger
(see [`docs/architecture.md`](docs/architecture.md)). Skeleton stubs are present for the
ledger module; behavior is not yet implemented.

### Changed
- **Receiving-document OCR is Claude-only.** The Google Gemini extractor and the `google-genai`
  dependency are removed. Extraction runs on **Claude Haiku 5.5** (`ANTHROPIC_MODEL`) with
  **Claude Sonnet 5.5** (`ANTHROPIC_FALLBACK_MODEL`) as fallback when Haiku errors, refuses, or
  returns no header fields; `ANTHROPIC_EFFORT` (default `medium`) sets how much the models think.
  The JSON shape now comes from structured outputs rather than a forced tool call, which the
  current Sonnet rejects. `OCRResponse.provider` now carries the answering model ID.
- The A8-4 bench (`scripts.ocr_bench.run_bench`) compares Claude models (`--model`, repeatable)
  instead of providers, and `baseline.json` holds a single model-agnostic accuracy `floor`.
- Settings ignore unknown `.env` keys, so a `backend/.env` still carrying `GEMINI_API_KEY` loads.

## [0.2.0-sprint1-baseline] — 2026-06-16

First tagged **Phase 2 engineering baseline** — a runnable, reproducible, documented reference
point for later sprints to compare against. No new product behavior; this release hardens the
engineering foundation on top of the Phase 1 feature surface.

### Added
- Root **`README.md`** with a cold-clone quickstart, environment reference, and command guide.
- **`CONTRIBUTING.md`** — branch strategy, naming, commit/tag conventions, artifact storage rules.
- **`docs/architecture.md`** — system decomposition, layering, and a repo→design map.
- **`docs/RISK_LOG.md`** — tracked engineering risks/issues with severity, mitigation, owner, status.
- **`KNOWN_ISSUES.md`** — current known limitations.
- **`scripts/smoke-test.sh`** — one-command end-to-end baseline check (DB → migrate → seed →
  backend → health/auth/RBAC → tests → frontend build).
- **`backend/.env.example`** and **`frontend/.env.local.example`** — sanitized config templates.
- Phase 2 skeleton stubs for the realigned **stock-movement ledger** module (model/service/router
  placeholders, no behavior yet).

### Fixed
- Pinned **`greenlet`** in `backend/requirements.txt` — required by SQLAlchemy's async engine on
  Python 3.13 but previously not captured, which broke a clean-environment install.

### Baseline (carried forward from Phase 1, GRAD 695)
The tagged tree already includes the Phase 1 surface, merged across tickets ACR-1…ACR-22:
- **Backend (FastAPI):** auth/JWT, RBAC privilege-union middleware, user management, masters
  (contacts, products), receiving with BOL duplicate guard, AI/OCR extraction service, inventory
  (lots + transactions + alerts + trace/export), work orders + allocation, shipments, and an
  append-only audit log. 8 Alembic migrations (`001`→`008`).
- **Frontend (Next.js 16):** login + auth flow, dashboard, inventory, receiving, master-data, and
  supporting module UIs; EN/ES i18n; shadcn/ui design system.
- **Quality gates:** pytest suite with an 85% coverage floor; Jest + lint + build, all run in CI.
- **Infrastructure:** Docker Compose PostgreSQL 15; `reset-db-and-seed.sh` for deterministic local data.

[Unreleased]: https://github.com/jesgueva/acra_dev/compare/v0.2.0-sprint1-baseline...HEAD
[0.2.0-sprint1-baseline]: https://github.com/jesgueva/acra_dev/releases/tag/v0.2.0-sprint1-baseline
