# Plan — ACR-42: Containerize the stack & pin runtime versions (A10-1 + A10-4)

**Status:** draft for review — **not implemented**
**Linear:** [ACR-42](https://linear.app/chronos-laboral/issue/ACR-42/a10-1-a10-4-containerize-the-stack-and-pin-runtime-versions) · High · Todo
**Parent:** [`plan_a8_a10_readiness.md`](./plan_a8_a10_readiness.md) §3.1, items **A10-1** and **A10-4**
**Written against:** `master` @ `7649a6e`, explored read-only in `acra-worktrees/wt-1`
**Date:** 2026-07-30
**Branch:** `ticket-42/docker-stack-versions`
**Size:** M — roughly 1.5–2 days
**Rubric hooks:** A10 Artifact Completeness 20 · Reproducibility & Setup 20

**Why the two items are one ticket:** a Dockerfile must name a base-image tag, so it cannot be
written before the Node and Python versions are settled. §4 of the parent plan already sequences
A10-4 → A10-1. Splitting them means writing the images twice.

---

## 1. Current state

Measured against `master` @ `7649a6e`, not recalled.

### 1.1 Containers — nothing exists

`docker-compose.yml:1-23` declares exactly one service:

```yaml
services:
  db:
    image: postgres:15
    ports: ["${ACRA_DB_PORT:-5433}:5432"]
    healthcheck: pg_isready -U postgres -d acra_db
```

- `find . -name "Dockerfile*"` → **0 results**. No `.dockerignore` anywhere.
- `docker compose up` therefore starts **Postgres only**; both app tiers are host processes started
  by hand (`README.md:72-75`).
- The `db` service already parameterizes its container name and host port
  (`ACRA_DB_CONTAINER`, `ACRA_DB_PORT`) so a second worktree can run alongside. **The new services
  must follow that same pattern** — 5433 is known to be squatted by an unrelated stack on this host.
- The `db` healthcheck already exists and is the model for the new ones.

### 1.2 Versions — four Node claims, three Python claims

| Source | Node | Python |
|---|---|---|
| root `.nvmrc` | **22** | — |
| `frontend/.nvmrc` | **24** | — |
| `frontend/package.json:6` `engines.node` | **>=24** | — |
| `frontend/package.json:43` `@types/node` | **^22** | — |
| `README.md:34-35` | ≥ 20 (verified 24) | ≥ 3.11 (verified 3.13) |
| `docs/architecture.md:163-164` | 24 / npm 11 | **3.13** |
| `.github/workflows/ci.yml:41` | (uses `frontend/.nvmrc`) | **3.12** |

**Root `.nvmrc` has zero consumers** — `grep -rn nvmrc` across the repo returns exactly one hit,
`ci.yml:67`, and it points at `frontend/.nvmrc`. The root file is vestigial drift.

### 1.3 Dependency pinning

`backend/requirements.txt` is 20 lines, 18 of them exact `==`. The two exceptions are the two
least deterministic dependencies in the project:

```
backend/requirements.txt:14   google-genai>=1.0.0
backend/requirements.txt:15   anthropic>=0.40.0
```

There is no backend lockfile and no `requires-python`. `frontend/package-lock.json` **does** exist
and CI already uses `npm ci` (`ci.yml:73`) — the frontend side of A10-4 is only the version
reconciliation, not a lockfile.

`docs/architecture.md:171-172` claims *"Backend dependencies are pinned in
`backend/requirements.txt`"*. That statement is currently **false** for those two lines.

### 1.4 Defect found while exploring — duplicate key in the env template

`backend/.env.example` declares `CORS_ORIGINS` **twice**: once with its explanatory comment block,
and again as a bare trailing line at the end of the file. The last wins, so behaviour is
accidentally correct today, but this is the file a clean-run user copies, and it is exactly the
class of thing A10's clean-environment pass is supposed to catch. Fix it here.

### 1.5 Constraints the containers must respect

These are the facts that decide the compose topology.

1. **`NEXT_PUBLIC_API_URL` is baked at build time.** `frontend/src/lib/api-client.ts:9` reads it,
   and any `NEXT_PUBLIC_*` var is inlined into the browser bundle by `next build`. The browser is
   on the **host**, not the compose network, so this must be the host-reachable
   `http://localhost:8000` and must be passed as a Docker **build arg**, not a runtime env var.
2. **`BACKEND_URL` is read at runtime, server-side.** `frontend/app/api/auth/login/route.ts:5-6`
   and `me/route.ts:5-6` use `process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ??
   "http://localhost:8000"`. This one runs *inside* the compose network and must be
   `http://backend:8000`.

   > Getting 1 and 2 the same way round is the single most likely way to ship a broken image: the
   > stack will look healthy and every login will fail, or vice versa.
3. **`alembic/env.py:16` is `os.environ["DATABASE_URL"]`** — a hard `KeyError` if unset. The
   migration step must have it explicitly; `alembic.ini:6`'s `sqlalchemy.url` is always overridden
   and is stale documentation (port 5432).
4. **CORS is env-driven.** `app/core/config.py:14` defaults `cors_origins` to
   `http://localhost:3000`; `main.py:24` feeds `settings.cors_origin_list` to `CORSMiddleware`. The
   backend container must receive the frontend's **browser-visible** origin.
5. **`frontend/next.config.mjs` has no `output` setting.** Without `output: "standalone"` the
   runtime image has to carry all of `node_modules`.
6. **`/health` already exists** (`app/main.py:83-85`) and needs no DB — good enough for the
   backend container healthcheck.

---

## 2. Decisions taken

Recorded here rather than raised as blocking questions, per the parent skill: each follows an
existing pattern in the repo.

| # | Decision | Rationale |
|---|---|---|
| D1 | **Node 24** everywhere | `frontend/.nvmrc` (the only file CI reads) is already 24, `engines` is `>=24`, and `architecture.md` verified 24. Root `.nvmrc` 22 is the outlier with zero consumers. |
| D2 | Root `.nvmrc` → **set to `24`**, not deleted | A repo-root `.nvmrc` is what `nvm use` picks up at the top level; keeping it aligned is more useful than removing it. `frontend/.nvmrc` stays the CI source of truth. |
| D3 | **Python 3.13** everywhere, CI moved 3.12 → 3.13 | Two of three sources already say 3.13, and `requirements.txt:4`'s comment (*"greenlet… not auto-installed on Python 3.13"*) is direct evidence 3.13 is the version actually exercised locally. Documenting a version CI never runs is the drift this ticket exists to remove. **Fallback:** if a dependency lacks 3.13 wheels, standardize on 3.12 instead and update README + architecture.md down to match — either way, one number. |
| D4 | Two-file backend dep model: `requirements.txt` (direct, fully `==`) + **`requirements.lock`** (full transitive closure, `pip freeze`) | Satisfies "lockfile-reproducible" without introducing pip-tools/uv as new tooling. Docker installs from the lock; humans edit `requirements.txt`. |
| D5 | Migrations run as a **one-shot `migrate` service**, backend gated on its success | Mirrors what `reset-db-and-seed.sh` already does in sequence. Keeps migration failure loud and separate from app boot. |
| D6 | Seed is **opt-in** behind a compose profile | `docker compose up` must not silently wipe/populate a database. `reset-db-and-seed.sh` stays the destructive path, by explicit invocation. |
| D7 | New services get overridable host ports, like `db` already has | `ACRA_DB_PORT` precedent at `docker-compose.yml:13`; port 5433 is known-squatted on this host. |

---

## 3. Change list

### CREATE

| File | Purpose |
|---|---|
| `backend/Dockerfile` | Multi-stage: `python:3.13-slim` base, install from `requirements.lock`, non-root user, `uvicorn app.main:app` on 8000. |
| `backend/.dockerignore` | Exclude `.venv/`, `__pycache__/`, `.pytest_cache/`, `.coverage`, `tests/`, `.env`. |
| `frontend/Dockerfile` | Multi-stage: deps (`npm ci`) → build (`next build` with `NEXT_PUBLIC_API_URL` **build arg**) → runtime on `node:24-alpine` from `output: "standalone"`, non-root, port 3000. |
| `frontend/.dockerignore` | Exclude `node_modules/`, `.next/`, `test-results/`, `playwright-report/`, `.env.local`. |
| `backend/requirements.lock` | Full transitive pin (D4), generated by `pip freeze` on Python 3.13. |
| `backend/tests/test_packaging.py` | The A10-4 regression guard — see §5.1. |
| `scripts/compose-smoke.sh` | Brings the composed stack up, waits for health, asserts `/health`, a login, and a frontend page render; tears down. Kept separate from `smoke-test.sh` so the existing 7-stage harness stays untouched. |
| `frontend/e2e/ticket-42.spec.ts` | Playwright spec exercising the flow against the running stack (§5.3). |
| `.env.example` (repo root) | Compose-level knobs: `ACRA_DB_PORT`, `ACRA_BACKEND_PORT`, `ACRA_FRONTEND_PORT`, `SECRET_KEY`, AI keys. |

### MODIFY

| File | Change |
|---|---|
| `docker-compose.yml` | Add `migrate` (one-shot), `backend`, `frontend` services; healthchecks; `depends_on` chain; `seed` profile (D5, D6); overridable host ports (D7). |
| `backend/requirements.txt` | Pin `google-genai` and `anthropic` to exact `==` versions. |
| `backend/pyproject.toml` *(create if absent)* | Add `requires-python = ">=3.13"`. Repo currently has only `backend/pytest.ini`; if adding `pyproject.toml` would disturb pytest discovery, put `requires-python` there and leave `pytest.ini` alone. |
| `.nvmrc` (root) | `22` → `24` (D2). |
| `frontend/package.json` | `@types/node` `^22` → `^24` to match the runtime. |
| `frontend/next.config.mjs` | Add `output: "standalone"`. |
| `.github/workflows/ci.yml` | `python-version: "3.12"` → `"3.13"` (D3). |
| `backend/.env.example` | Remove the duplicate trailing `CORS_ORIGINS` line (§1.4). |
| `backend/alembic.ini` | Stale `sqlalchemy.url` port 5432 → 5433, matching the documented compose port (parent plan §7). |
| `README.md` | New "Run with Docker" section alongside the existing local quickstart; correct the Prerequisites version lines to the single Node/Python numbers. |
| `docs/architecture.md` | Version-snapshot table → Python 3.13; the "Backend dependencies are pinned" claim becomes true, and gains the `requirements.lock` reference. |
| `CLAUDE.md` | Note the container path and the single Node/Python versions. |
| `.gitignore` | Ignore the stray root `*.png` screenshots (currently untracked but polluting `git status`). |

**No `app/` module is created or modified.** The backend coverage floor is therefore unaffected —
this ticket adds no new `app.*` lines to cover. Stated explicitly so the ≥85% gate result is not
mistaken for a regression.

---

## 4. Compose topology

```
db (postgres:15, healthcheck pg_isready)
  └─> migrate  (backend image, one-shot: alembic upgrade head, DATABASE_URL=…@db:5432)
        └─> backend  (uvicorn :8000, healthcheck GET /health)
              └─> frontend  (next start :3000)

  [profile: seed]  seed (backend image, one-shot: python scripts/seed_fake_data.py)
```

Env split that makes or breaks it (§1.5):

| Service | Variable | Value | When read |
|---|---|---|---|
| `migrate` / `backend` / `seed` | `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@db:5432/acra_db` | runtime |
| `backend` | `CORS_ORIGINS` | `http://localhost:${ACRA_FRONTEND_PORT:-3000}` | runtime |
| `frontend` | `NEXT_PUBLIC_API_URL` | `http://localhost:${ACRA_BACKEND_PORT:-8000}` | **build arg** |
| `frontend` | `BACKEND_URL` | `http://backend:8000` | runtime |

---

## 5. Test plan

Tests are written **with** each piece, not batched at the end.

### 5.1 `backend/tests/test_packaging.py` — the A10-4 guard

No DB, no fixtures; each reads a repo file and asserts a parity invariant. These are the tests that
stop the drift from silently coming back.

| Test | Asserts |
|---|---|
| `test_node_version_is_consistent` | root `.nvmrc`, `frontend/.nvmrc`, and `engines.node` all resolve to major **24**. |
| `test_types_node_matches_runtime` | `@types/node` major matches the Node major. |
| `test_all_backend_requirements_are_exactly_pinned` | every non-comment line in `requirements.txt` uses `==` — parameterized, so the failure message names the offending package. Directly guards the `google-genai` / `anthropic` regression. |
| `test_lockfile_covers_every_direct_requirement` | every distribution named in `requirements.txt` appears in `requirements.lock`. |
| `test_requires_python_matches_ci` | declared `requires-python` major.minor == `ci.yml`'s `python-version`. |
| `test_env_example_has_no_duplicate_keys` | regression test for §1.4, run over **both** `.env.example` templates. |

### 5.2 Container / integration

| Check | How |
|---|---|
| Both images build | `docker compose build` in the gate. |
| Migrations apply in-container | `migrate` service exits 0; `alembic current` shows `014`. |
| Backend serves | `GET /health` → 200 through the mapped host port. |
| Auth works through the container network | `POST /api/v1/auth/login` with `admin`/`admin123` → 200 + JWT (after `--profile seed`). |
| Frontend renders | `GET /en` → 200 with real markup, not an error page. |
| **The build-arg trap (§1.5)** | Assert the browser bundle contains the *host* API URL, and that a login through the UI succeeds — this is what catches `NEXT_PUBLIC_API_URL` being wired to `backend:8000` by mistake. |
| Clean-run reproducibility | `docker compose down -v` then up again from scratch. |

Automated in `scripts/compose-smoke.sh`.

### 5.3 Playwright — `frontend/e2e/ticket-42.spec.ts`

Against the **composed stack** (which is a production `next start`, satisfying KI-02's
"never `next dev`" rule):

- login as `admin` → lands on the dashboard;
- an authenticated data page loads real rows from the containerized backend;
- `/en/` and `/es/` both render with correct copy;
- no console errors and no 5xx in the network log.

### 5.4 Frontend unit tests

**None added, deliberately.** This ticket adds no React component and no client module — the only
frontend source change is `next.config.mjs`. Inventing a Jest test here would test the framework,
not the change. The `next.config.mjs` change is covered by `npm run build` and by §5.2/§5.3.

### 5.5 Full gate (unchanged, must stay green)

`pytest tests/ --cov=app --cov-fail-under=85` · `npx jest` · `npm run lint` · `npm run build` ·
`./scripts/smoke-test.sh` · the new `./scripts/compose-smoke.sh` · the Playwright spec.

---

## 6. Live verification

1. From a clean clone: `cp .env.example .env`, then `docker compose up --build -d`.
2. `docker compose --profile seed run --rm seed`.
3. Open `http://localhost:3000` → redirected to `/en/login`.
4. Log in as `admin` / `admin123` → dashboard renders with seeded numbers.
5. Navigate to Inventory → lots load from the containerized backend (network panel shows
   `localhost:8000`, **not** `backend:8000`).
6. Switch to `/es/` → Spanish copy; toggle the theme → both render.
7. `docker compose down -v && docker compose up -d` → migrations re-apply cleanly on an empty
   volume.
8. Console and network panels clean throughout.

---

## 7. Risks / open questions

| # | Risk | Mitigation |
|---|---|---|
| R1 | **Python 3.13 wheels.** Moving CI 3.12 → 3.13 could fail on a dependency without wheels. | The greenlet comment is evidence 3.13 already works locally. If CI fails, fall back to D3's alternative: standardize on 3.12 and correct README + architecture.md downward. Either way one number, which is the acceptance criterion. |
| R2 | **`@types/node` ^22 → ^24 may surface new type errors** in `next build`. | The build gate catches it. If it breaks, leave `@types/node` pinned at 22 and record the exception in the PR — the runtime Node version is what the ticket is actually about. |
| R3 | **Host ports 5433 / 8000 / 3000 may be occupied** — 5433 is known-squatted on this machine. | D7: every host port overridable (`ACRA_DB_PORT`, `ACRA_BACKEND_PORT`, `ACRA_FRONTEND_PORT`), following the existing `db` pattern. |
| R4 | **Image build time** could make the gate slow. | Multi-stage with cached dependency layers; `.dockerignore` keeps context small. |
| R5 | `NEXT_PUBLIC_API_URL` build-arg baking makes the frontend image **environment-specific**. | Accept for now — it is inherent to `NEXT_PUBLIC_*`. Document it in the README Docker section as a known property, not a bug. |

**Open question for the reviewer (non-blocking — I will proceed with the stated default):**

> Should the backend healthcheck stay on the DB-agnostic `/health`, or should this ticket add a
> `/ready` that also checks the database? **Default: keep `/health`.** Adding `/ready` means new
> `app.*` code, which pulls the coverage floor into a packaging ticket. If you want `/ready`, say
> so and I will fold it in with its own tests.

---

## 8. Build order

1. **A10-4 first** — reconcile Node (D1, D2, `@types/node`), pick Python (D3), pin the two AI SDKs,
   generate `requirements.lock`, add `requires-python`, fix the duplicate `CORS_ORIGINS`.
2. Write `backend/tests/test_packaging.py` and make it pass. *(commit)*
3. `backend/Dockerfile` + `.dockerignore`; build it; run `alembic upgrade head` in-container against
   the compose `db`. *(commit)*
4. `next.config.mjs` → `output: "standalone"`; `frontend/Dockerfile` + `.dockerignore`; build it,
   confirm the build arg lands in the bundle. *(commit)*
5. Extend `docker-compose.yml` — `migrate`, `backend`, `frontend`, healthchecks, `depends_on`,
   `seed` profile, overridable ports; root `.env.example`. *(commit)*
6. `scripts/compose-smoke.sh`; run it clean. *(commit)*
7. `frontend/e2e/ticket-42.spec.ts` + live Playwright exploration. *(commit)*
8. Docs — README Docker section, architecture.md snapshot, CLAUDE.md, alembic.ini, `.gitignore`.
   *(commit)*
9. CI `python-version` → 3.13. *(commit)*
10. Full gate, then draft PR ending `Closes ACR-42`.

---

## 9. Acceptance criteria → coverage map

| AC (from ACR-42) | Covered by |
|---|---|
| 1. `docker compose up` brings up all three tiers, app reachable and loginable | §3 compose changes · §5.2 · §6 |
| 2. Migrations run against the composed DB | D5 `migrate` service · §5.2 |
| 3. Exactly one Node and one Python version repo-wide | D1–D3 · `test_packaging.py` §5.1 |
| 4. `google-genai` + `anthropic` pinned exactly | `requirements.txt` · `test_all_backend_requirements_are_exactly_pinned` |
| 5. Backend deps lockfile-reproducible | D4 `requirements.lock` · `test_lockfile_covers_every_direct_requirement` |
| 6. README documents the container path | §3 MODIFY |
| 7. Existing gates stay green | §5.5 |
