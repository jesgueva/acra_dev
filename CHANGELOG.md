# Changelog

All notable changes to ACRA MES are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Phase 2 realignment toward the append-only `StockMovement` ledger
(see [`docs/architecture.md`](docs/architecture.md)). Skeleton stubs are present for the
ledger module; behavior is not yet implemented.

### Added
- **Railway deployment, EU West (Amsterdam)** — `.railway/railway.ts` defines the production stack
  (Postgres 15, backend with migrations as its pre-deploy step, frontend) as Railway
  Infrastructure as Code, every resource pinned to `europe-west4-drams3a`. Secrets are declared
  but never valued in the file. `.railway/check.ts` validates region pinning, secret handling,
  backend URL wiring and ports offline; `.github/workflows/railway-iac.yml` runs it on every change
  and, once opted in, plans/applies via Railway's action. Runbook: `docs/DEPLOY_RAILWAY.md`.
- **`backend/scripts/bootstrap_admin.py`** — creates (or resets) a `company_admin` on a deployed
  database without the demo data or demo passwords, granting the seed's role privileges.
- **`APP_ENV=production`** — the API refuses to start with a missing, default or short
  `SECRET_KEY`.

### Security
- Upgraded backend and frontend dependencies to clear known advisories. The backend lock carried
  75 (Starlette, python-multipart, Pillow, python-jose, anyio, urllib3, certifi, cryptography,
  pytest); `npm audit` reported 30, 3 critical and 17 high (Next.js, axios, next-intl, PostCSS and
  transitive packages). Two remain with no upstream fix: python-jose GHSA-3qf3-8w2g-rqmx and its
  `ecdsa` dependency's CVE-2024-23342. Neither is reachable the way this app uses JWTs (HS256 with
  a symmetric secret and a pinned algorithm list; nothing is signed with ECDSA).

### Changed
- **Backend:** FastAPI 0.115 → 0.162 (Starlette 0.41 → 1.10), SQLAlchemy 2.0 → 2.1, uvicorn
  0.32 → 0.54, Pydantic 2.10 → 2.14, Alembic 1.14 → 1.20, anthropic 0.119 → 2.3, google-genai
  1.2 → 2.33, pytest 8 → 9, pytest-asyncio 0.24 → 1.4, Pillow 11 → 13; `requirements.lock`
  regenerated. `HTTP_422_UNPROCESSABLE_ENTITY` → `HTTP_422_UNPROCESSABLE_CONTENT` (Starlette 1.x
  deprecation; same status code). **Behavior change from FastAPI:** a request with no bearer token
  (or a non-Bearer scheme) now gets `401` with `WWW-Authenticate: Bearer` instead of `403`.
  Authenticated requests lacking a privilege still get `403`. The frontend interceptor already
  treats both the same way.
- **Frontend:** Next.js 16.2 → 16.4, React 19.2 → 19.3, axios 1.15 → 1.20, next-intl 4.9 → 4.14,
  TypeScript 5.9 → 6.0 (`tsconfig.json` now sets `rootDir`, which TS 6 requires), jest-dom 6 → 7,
  Playwright 1.61 → 1.64. `shadcn` moved to `devDependencies` — it is only needed at build time.
  ESLint stays on 9 (now marked unsupported upstream): the React, import and jsx-a11y plugins that
  `eslint-config-next` pulls in do not declare ESLint 10 support yet.

### Removed
- `passlib` — never imported. `bcrypt`, which `app/core/security.py` calls directly, is now
  declared instead of arriving transitively.
- `autoprefixer` — unused; Tailwind v4's PostCSS plugin handles prefixing.

### Fixed
- Six type errors in frontend test files, which Next.js 16.4's build-time type check now reports.

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
