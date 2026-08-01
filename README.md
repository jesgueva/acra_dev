# ACRA MES

**ACRA Integrated Manufacturing Execution System** — a state-aware MES for a single-facility
packaging manufacturer. Tracks inbound receiving (with AI-assisted document extraction), live
inventory by lot, work orders, production/forklift worksheets, and shipments, with role-based
access control, an append-only audit trail, and a bilingual (EN/ES) UI.

This is a **monorepo**: a FastAPI backend, a Next.js frontend, and a PostgreSQL database, with
Docker Compose for local infrastructure.

> **Status:** Phase 2 engineering baseline (`v0.2.0-sprint1-baseline`). The Phase 1 feature
> surface is merged and CI-gated; Phase 2 realigns inventory onto an append-only `StockMovement`
> ledger (see [`docs/architecture.md`](docs/architecture.md)).

---

## Tech stack

| Layer | Stack |
|---|---|
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript 5, Tailwind CSS v4, shadcn/ui, next-intl, TanStack Query, Axios |
| **Backend** | FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, python-jose (JWT), passlib/bcrypt |
| **Database** | PostgreSQL 15 |
| **AI extraction** | Hosted vision-LLM for receiving-document OCR (Google Gemini → Anthropic Claude fallback) |
| **Tests / CI** | pytest (85% coverage floor), Jest + Testing Library, GitHub Actions |

---

## Prerequisites

**If you run the stack with Docker (below), you only need Docker and git** — Python and Node come
from the images.

For a local (non-container) install, these are the supported versions. They are the *only* versions
named anywhere in this repo — `backend/pyproject.toml` and `.nvmrc` are the machine-readable source
of truth, and `backend/tests/test_packaging.py` fails the build if a doc drifts from them.

- **Python** 3.13 — declared in [`backend/pyproject.toml`](backend/pyproject.toml)
- **Node.js** 24 + npm — declared in [`.nvmrc`](.nvmrc) / [`frontend/.nvmrc`](frontend/.nvmrc)
- **Docker** with the Compose plugin (`docker compose`)
- **git**

You do **not** need a local PostgreSQL install — Docker Compose provides it on host port **5433**.

---

## Quickstart A — Docker (whole stack, no toolchain install)

Clean clone to running system in three commands. Nothing but Docker and git required.

```bash
git clone git@github.com:jesgueva/acra_dev.git
cd acra_dev
cp .env.example .env                            # defaults work as-is for local use

docker compose up -d --build                    # Postgres + migrations + API + web
docker compose --profile seed run --rm seed     # demo data (opt-in)
```

Open **http://localhost:3000** and sign in with a [seeded account](#seeded-demo-logins). The API is
at **http://localhost:8000** (docs at `/docs`).

| Service | What it does |
|---|---|
| `db` | PostgreSQL 15, published on `5433` |
| `migrate` | One-shot `alembic upgrade head`, then exits. The API waits for it to succeed. |
| `backend` | FastAPI on `8000` |
| `frontend` | Next.js production server on `3000` |
| `seed` | Demo data. Behind the `seed` profile, so `up` never repopulates a database by surprise. |

Useful commands:

```bash
docker compose logs -f backend        # follow a service
docker compose run --rm backend pytest tests/   # run the suite with no local Python*
docker compose down                   # stop, keep data
docker compose down -v                # stop and wipe the database volume
./scripts/compose-smoke.sh            # assert the containerized stack end to end
```

\* Expect **`379 passed, 7 skipped`**. The backend image is built from `backend/` alone, so files
outside that directory — `.nvmrc`, `frontend/package.json`, `.github/workflows/ci.yml`,
`frontend/Dockerfile`, and the frontend/root `.env.example` templates — are not in the image. The
`backend/tests/test_packaging.py` checks that compare against them skip here and run normally on a
checkout and in CI. Nothing is failing; that skip count is the expected result.

**If a port is already taken** (common — this repo is often checked out into several worktrees),
override it in `.env` or inline:

```bash
ACRA_DB_PORT=5442 ACRA_BACKEND_PORT=8042 ACRA_FRONTEND_PORT=3042 \
  docker compose -p acr42 up -d --build
```

> **Changing `ACRA_BACKEND_PORT` requires `--build`, not just a restart.** `NEXT_PUBLIC_API_URL` is
> compiled into the browser bundle at build time rather than read at runtime, so the frontend image
> is tied to the API port it was built for. This is a property of Next.js's `NEXT_PUBLIC_*`
> handling, not a bug in the compose file.

---

## Quickstart B — Local processes (for active development)

Use this when you want hot reload. Requires the Python and Node versions listed above.

```bash
# 1. Clone
git clone git@github.com:jesgueva/acra_dev.git
cd acra_dev

# 2. Environment files (copy templates, then fill in secrets — see "Environment" below)
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local

# 3. Backend dependencies (isolated virtualenv)
#    requirements.lock is the full resolved set — it is what CI and the containers install, so
#    installing it gets you exactly their versions. Use requirements.txt only when ADDING a
#    dependency, then regenerate the lock (see backend/requirements.lock's header).
cd backend
python3 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r requirements.lock
cd ..

# 4. Frontend dependencies
cd frontend
npm install
cd ..

# 5. Start PostgreSQL, apply migrations, and load demo data (one script)
./scripts/reset-db-and-seed.sh

# 6. Run the backend (terminal 1)
cd backend && ./.venv/bin/uvicorn app.main:app --reload --port 8000

# 7. Run the frontend (terminal 2)
cd frontend && npm run dev
```

Then open **http://localhost:3000** and sign in with a seeded account (below). The API is at
**http://localhost:8000**, with interactive docs at **http://localhost:8000/docs**.

### Seeded demo logins

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Company Admin |
| `supervisor1` | `demo123` | Production Supervisor |
| `clerk1` | `demo123` | Receiving/Shipping Clerk |
| `operator1` / `operator2` | `demo123` | Machine Operator |

> Demo credentials seed a **local** database only. Never reuse them outside local development.

---

## Verify it works (smoke test)

One command takes a clean checkout to a running stack and asserts the core path end to end —
database up, migrations + seed, backend boot, `/health`, login + JWT, RBAC enforcement, an
authenticated read, the backend test subset, and a frontend production build:

```bash
./scripts/smoke-test.sh
```

It exits `0` only if every stage passes. Flags: `SMOKE_SKIP_FRONTEND=1` (backend only),
`SMOKE_SKIP_RESET=1` (don't wipe/reseed), `SMOKE_BACKEND_PORT=8001`.

For a fuller, evidence-capturing pass — environment snapshot, API route inventory, smoke test,
full backend suite + coverage, a **data-pipeline integrity trace**, a **real OCR round-trip**, and
an **API latency benchmark** — run the validation harness (used for the Hard Stop 3 validation
package):

```bash
./scripts/validation-run.sh            # writes artifacts to ./validation-evidence/
```

The OCR round-trip needs `GEMINI_API_KEY` (and optionally `ANTHROPIC_API_KEY`) in `backend/.env`;
it is skipped with a clear notice if no key is present.

### Benchmarks and request logs

Latency numbers come from one place, `app/core/benchmark.py`, so they stay comparable: nearest-rank
p50/p95/p99 plus a provenance record (git SHA, host, Python, database, UTC timestamp, exact command)
stamped onto every artifact. Database credentials are stripped from the recorded DSN.

Run the API benchmark on its own against an already-running backend:

```bash
PYTHONPATH=backend python scripts/validation/api_latency_bench.py validation-evidence \
  --requests 100 [--base-url http://localhost:8000]
```

It writes `validation-evidence/api-latency-<endpoint>.{json,txt}` — the text carries the
human-readable header, the JSON keeps the raw samples so a later regression gate can recompute
rather than trust the summary. It reports latency and does not enforce a budget; the asserted budget
gate lives in `backend/tests/integration/test_reservation_availability.py` (RSK-04).

The API also logs one line per request (method, route **template**, status, duration, request id).
Set `LOG_FORMAT=json` in `backend/.env` for one JSON object per line; the default `text` keeps the
human-readable console format. Every response carries an `X-Request-ID` header — supply your own to
trace a specific call through the logs:

```bash
curl -i -H 'X-Request-ID: my-trace-1' localhost:8000/health
```

One limitation worth knowing: a `500` from an unhandled exception is produced by Starlette's
`ServerErrorMiddleware`, which wraps *outside* the CORS layer. That response carries the
`X-Request-ID` header on the wire, but cross-origin browser JavaScript cannot read it because the
response has no `Access-Control-Allow-Origin`. Read the id from the server log or from a same-origin
request. This is a property of the app's pre-existing error handling, not of the request logging.

---

## Implementation status

What a reader can exercise **right now** vs. what is still partial at this baseline
(`v0.2.0-sprint1-baseline`). Re-verified end to end on 2026-06-23 via `scripts/validation-run.sh`.

| Capability | State | Notes |
|---|---|---|
| Auth (JWT) + RBAC + EN/ES i18n | ✅ Live (UI + API) | Anonymous reads rejected (401/403); privileges resolved per request. |
| Receiving + AI OCR (Gemini → Claude) | ✅ Live (UI + API) | BOL upload auto-fills the form; duplicate-BOL guard; pallet × units leftover reconciliation; runnable with no API key via `OCR_MOCK_MODE` (see Environment below). |
| Inventory (filter / adjust / split / move / CSV / alerts / trace) | ✅ Live (UI + API) | On-hand stored as integer ×100; per-lot transaction log. |
| Master data (contacts, products), Dashboard | ✅ Live (UI + API) | |
| Work Orders (incl. SERIALIZABLE FIFO allocation), Users, Audit-log read | ⚙️ Backend complete, **UI placeholder** | Endpoints + tests exist; pages render "Coming Soon"; nav links commented out. |
| Shipments | ⚙️ Backend complete, **not reachable** | Endpoints + UI exist, but `shipping.*` privileges are unseeded → 403 for all roles (KI-08). |
| StockMovement ledger (C-04); Production / Forklift worksheets (C-06 / C-07) | 🚧 Phase-2 stub | Ledger model/service/router are placeholders (`501` / `NotImplementedError`, KI-04); inventory still runs on the Phase-1 lot model. |

Known rough edges are tracked in [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) and [`docs/RISK_LOG.md`](docs/RISK_LOG.md).

---

## Environment

Configuration is via env files (both are git-ignored; commit only the `.example` templates).

### `backend/.env` — copy from [`backend/.env.example`](backend/.env.example)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Async SQLAlchemy DSN. Use port **5433** with the Docker Compose Postgres. |
| `SECRET_KEY` | JWT signing key — generate a unique random value. |
| `ALGORITHM` | JWT algorithm (`HS256`). |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime. |
| `GEMINI_API_KEY` | Google Gemini key for receiving-document extraction (primary). |
| `ANTHROPIC_API_KEY` | Anthropic Claude key (extraction fallback). |
| `OCR_MOCK_MODE` | `true`/`false` (default `false`). See "Running OCR without an API key" below. |
| `LOG_FORMAT` | `text` (default, human-readable) or `json` (one structured object per request line). |

The AI keys are only exercised by the receiving/OCR flow — the rest of the app runs without them.

#### Running OCR without an API key

Set `OCR_MOCK_MODE=true` (`backend/.env`, or `OCR_MOCK_MODE=true docker compose up -d` for the
containerized stack) and the receiving/OCR endpoint returns a canned extraction result instead of
calling Gemini/Claude — no key needed, no network call made. Upload
[`backend/tests/fixtures/ocr/sample_bol_gridded.png`](backend/tests/fixtures/ocr/sample_bol_gridded.png)
on the Receiving page to see it end-to-end; every upload gets the same response regardless of
content. Leave it unset/`false` to use the real providers.

### `frontend/.env.local` — copy from [`frontend/.env.local.example`](frontend/.env.local.example)

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | Backend URL the browser calls (default `http://localhost:8000`). |
| `BACKEND_URL` | Backend URL the Next.js server-side auth proxy calls. |

---

## Common commands

```bash
# Backend tests (full suite; needs the DB up + DATABASE_URL set for schema tests)
cd backend && ./.venv/bin/python -m pytest tests/ -q

# Backend tests with coverage (CI enforces an 85% floor on app.*)
cd backend && ./.venv/bin/python -m pytest tests/ --cov=app --cov-report=term-missing

# Frontend tests / lint / build  (no "test" npm script — invoke jest directly, as CI does)
cd frontend && npx jest
cd frontend && npm run lint
cd frontend && npm run build

# Reset the database to clean seeded state (wipes the Docker volume)
./scripts/reset-db-and-seed.sh
```

### Seeding at volume

`seed_fake_data.py` takes a scale knob, so the same fixture can be grown for benchmarking. All
arguments are forwarded through `reset-db-and-seed.sh`.

```bash
./scripts/reset-db-and-seed.sh --scale 50    # 1 200 deliveries / 3 600 lots / 400 work orders
cd backend && ./.venv/bin/python scripts/seed_fake_data.py --help
```

| Flag | Default | Effect |
|---|---|---|
| `--scale N` | `1` | Multiplies both volume axes: 24 deliveries and 8 work orders per unit |
| `--deliveries N` | from `--scale` | Absolute delivery count, overriding `--scale` on that axis |
| `--work-orders N` | from `--scale` | Absolute work-order count (`0` builds a lots-only corpus) |
| `--materials M` | `6` | Size of the raw-material catalogue, for stressing per-product aggregation |
| `--json` | off | Machine-readable summary (params, elapsed, per-table counts) |

Two properties the seeder guarantees, both covered by `backend/tests/test_seed_scaling.py`:

- **`--scale 1` is the demo fixture**, byte-for-byte. The e2e suite reads these exact rows, so the
  default output is pinned by a golden-snapshot test.
- **Scale N is a superset of scale 1.** Deliveries are generated from the row index with no RNG, so
  re-running at a higher scale adds rows rather than conflicting with existing ones.

Only the bare invocation reproduces the demo fixture — every flag in the table above changes the
rows the e2e suite reads. `--materials` does so in **either** direction: lowering it drops materials
from the catalogue just as surely as raising it adds them.

Raising `--materials` also dilutes supply for the six materials work orders consume. Pair it with
`--work-orders 0` or more `--deliveries`; if allocation runs short the seeder aborts before
committing anything and names the knob to turn.

---

## Repository layout

```
acra_dev/
├── backend/            # FastAPI app (router → service → repository), Alembic, pytest
│   ├── app/            #   main.py, core/ (config, db, security, rbac, audit), models, routers, schemas, services
│   ├── alembic/        #   migrations (versions/)
│   ├── scripts/        #   seed_fake_data.py (--scale N for volume)
│   └── tests/          #   pytest suite (+ integration/)
├── frontend/           # Next.js 16 App Router + shadcn/ui
│   ├── app/            #   [locale]/ routes, api/auth/ server proxies, layout
│   ├── src/            #   components, contexts, lib, i18n
│   └── messages/       #   next-intl catalogs (en.json, es.json)
├── scripts/            # reset-db-and-seed.sh, smoke-test.sh, validation-run.sh, validation/
├── docs/               # architecture.md, RISK_LOG.md
├── docker-compose.yml  # full stack: db → migrate → backend → frontend (+ seed profile)
├── CHANGELOG.md · KNOWN_ISSUES.md · CONTRIBUTING.md
└── CLAUDE.md           # engineering memory (conventions, patterns)
```

See [`docs/architecture.md`](docs/architecture.md) for how this layout maps to the system design,
and [`CONTRIBUTING.md`](CONTRIBUTING.md) for branch strategy and conventions.

---

## Documentation

| Document | What it covers |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | System decomposition, layering, repo→design map, version snapshot |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Branch strategy, naming, commits, tags, artifact storage, PR/CI flow |
| [`CHANGELOG.md`](CHANGELOG.md) | Notable changes per release (Keep a Changelog) |
| [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) | Current known limitations and rough edges |
| [`docs/RISK_LOG.md`](docs/RISK_LOG.md) | Tracked engineering risks and issues |
| [`docs/DATA_PROVENANCE.md`](docs/DATA_PROVENANCE.md) | Where seed/demo/corpus data comes from and what cannot be redistributed |
| [`CLAUDE.md`](CLAUDE.md) | Detailed engineering memory and code conventions |

## License

MIT — see [`LICENSE`](LICENSE). The grant covers this repository's source code only; it does not
cover `frontend/acra_logo.png` (see [`docs/DATA_PROVENANCE.md`](docs/DATA_PROVENANCE.md)).
