# Deploying to Railway (EU)

The production deployment of the whole stack — Postgres, the FastAPI backend and the Next.js
frontend — on [Railway](https://railway.com), every resource pinned to **EU West (Amsterdam),
`europe-west4-drams3a`**. It is the cloud counterpart of `docker-compose.yml`; see
[`RUNBOOK.md`](RUNBOOK.md) for the local stack.

Everything that can be code is code, in [`.railway/railway.ts`](../.railway/railway.ts) (Railway
[Infrastructure as Code](https://docs.railway.com/infrastructure-as-code), applied with the Railway
CLI). This page is the part that can't be: the one-time bootstrap, the secrets, and day-2 operations.

```
                      Railway project "acra-mes" — europe-west4-drams3a (Amsterdam)
  browser ──https──▶ frontend (Next.js, :3000) ──http, private network──▶ backend (FastAPI, :8000)
     │                 healthcheck /en/login         BACKEND_URL           healthcheck /health
     │                                                                     pre-deploy: alembic upgrade head
     └──────────────────────https, NEXT_PUBLIC_API_URL────────────────────▶      │
                                                                                 ▼ private network
                                                                    Postgres 15 (postgres-ssl:15, volume)
```

## What is in code, and what is not

| Thing | Where it lives |
|---|---|
| Project, the three services, Postgres, region, build/deploy settings, healthchecks, migrations, every non-secret variable | `.railway/railway.ts` |
| `SECRET_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` | Set once with the CLI ([Secrets](#4-set-the-secrets)). Declared in `railway.ts` as `preserve()` — names only, never values. |
| The generated `*.up.railway.app` domains | `railway domain` ([step 5](#5-generate-the-public-domains)). Railway keeps generated domains out of IaC by design. Custom domains *are* in code. |
| The first administrator | `backend/scripts/bootstrap_admin.py` ([step 7](#7-create-the-first-administrator)) |
| Database backups | Dashboard ([step 9](#9-turn-on-database-backups)) |

`railway.ts` is authoritative: **anything missing from it is deleted on the next apply** — including
a variable someone added in the dashboard. Add variables to the file (as a literal, or as
`preserve()` for a secret), never only in the dashboard.

What the file sets, and why each one matters:

| Service | Setting | Why |
|---|---|---|
| all | `replicas: { "europe-west4-drams3a": 1 }` | Region pinning. `check.ts` fails CI if any service, database or volume names another region — or none, which means Railway's default. |
| all | source `jesgueva/acra_dev@master`, `checkSuites: true` | Autodeploy on merge, but only after the commit's GitHub Actions pass ("Wait for CI"). |
| backend | `preDeploy: alembic upgrade head` | Replaces compose's `migrate` job. A failed migration fails the deploy; the previous one keeps serving. |
| backend | `APP_ENV=production` | The API refuses to boot on a missing, default or < 32-character `SECRET_KEY` instead of signing JWTs with the default committed in `app/core/config.py`. |
| backend | `DATABASE_URL=postgresql+asyncpg://${{Postgres.PGUSER}}:…@${{Postgres.PGHOST}}…` | Railway's own `DATABASE_URL` uses the `postgresql://` scheme; the app needs the asyncpg dialect. Private network only. |
| backend | `CORS_ORIGINS=https://${{frontend.RAILWAY_PUBLIC_DOMAIN}}` | The browser origin. A mismatch shows up as every XHR CORS-blocked. |
| backend | `FORWARDED_ALLOW_IPS=*` | TLS ends at Railway's edge; without this uvicorn ignores `X-Forwarded-Proto` and FastAPI's redirects point at `http://` (blocked as mixed content). |
| backend | `LOG_FORMAT=json` | One structured line per request in `railway logs`. |
| frontend | `NEXT_PUBLIC_API_URL=https://${{backend.RAILWAY_PUBLIC_DOMAIN}}` | **Build time** — Railway passes it to the Dockerfile's `ARG`, and Next.js inlines it into the browser bundle. Changing it requires a rebuild. |
| frontend | `BACKEND_URL=http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:8000` | **Runtime** — the server-side auth proxy (`app/api/auth/*`), over the private network. |
| backend, frontend | `PORT=8000` / `PORT=3000` | Tells Railway which port to route and health-check. `check.ts` asserts each matches its Dockerfile's `EXPOSE`. |

The last three rows are CLAUDE.md's "one gotcha" in Railway's vocabulary; `check.ts` fails if the
two backend URLs are pointed the wrong way round.

## Prerequisites

- A Railway workspace, with the [Railway GitHub app](https://github.com/apps/railway-app) given access
  to `jesgueva/acra_dev` (services build from the repo).
- The Railway CLI, **5.42.1 or newer** (the IaC engine ships in the CLI; these steps were written
  against 5.71.0): `npm install -g @railway/cli@5.71.0`
- Node 24 (`.nvmrc`) — the CLI evaluates `railway.ts` with the `node` on your `PATH`.
- Python 3, only to generate `SECRET_KEY` below (any CSPRNG will do).

## One-time bootstrap

Run from the repo root.

### 1. Install and check the IaC locally

```bash
npm ci --prefix .railway
npm --prefix .railway run verify   # typecheck + invariants; needs no Railway account
```

### 2. Create the project

```bash
railway login
railway init --name acra-mes      # creates the project + its "production" environment, links this directory
```

### 3. Plan, then apply

```bash
railway config plan               # expect: create Postgres, backend, frontend
railway config apply
```

The first deploys **are expected to be wrong**, and steps 4–6 fix them:

- `backend` fails to start: `SECRET_KEY` is not set yet, and `APP_ENV=production` refuses to boot
  without it. That is the guard working.
- `frontend` builds before `backend` has a public domain, so its bundle points at `https://` with no
  host.
- If `backend`'s pre-deploy migration ran before Postgres finished starting, it fails too — the
  redeploy in step 6 covers that as well.

### 4. Set the secrets

Values go through stdin, so they never land in shell history or in this repo. `--skip-deploys`
because step 6 redeploys once, at the end.

```bash
# Required. 48 random bytes, URL-safe. Rotating it later signs everyone out.
python3 -c "import secrets; print(secrets.token_urlsafe(48), end='')" \
  | railway variable set SECRET_KEY --stdin --service backend --skip-deploys

# Optional — only the receiving-document OCR needs them. Paste the key, then Ctrl-D.
railway variable set GEMINI_API_KEY --stdin --service backend --skip-deploys
railway variable set ANTHROPIC_API_KEY --stdin --service backend --skip-deploys
```

Without the two API keys every module works except AI extraction on the Receiving page. Read
[EU data residency](#eu-data-residency) before setting them.

### 5. Generate the public domains

```bash
railway domain --service backend --port 8000
railway domain --service frontend --port 3000
```

Note both URLs. (For your own domain instead, see [Custom domains](#custom-domains).)

### 6. Redeploy with everything in place

```bash
railway redeploy --service backend --yes                  # picks up SECRET_KEY and CORS_ORIGINS
railway redeploy --service frontend --from-source --yes   # REBUILDS, baking in the backend URL
```

`--from-source` matters: a plain redeploy reuses the existing image, whose bundle still has the empty
API host from step 3.

### 7. Create the first administrator

A migrated database has roles but no users. **Do not run `seed_fake_data.py` here** — it also writes
demo deliveries and work orders plus five logins whose passwords are in the README.
`bootstrap_admin.py` grants the same role privileges as the seed and creates one administrator,
with a password you choose:

```bash
railway ssh --service backend
# then, inside the container:
python scripts/bootstrap_admin.py --username <you> --full-name "<Your Name>"   # prompts for the password twice
```

Create everyone else from **Users** in the app. Re-running the script for an existing username
resets that password and re-activates the account — the recovery path for a locked-out admin.

### 8. Verify

```bash
curl -fsS https://<backend-domain>/health          # {"status":"ok"}
railway logs --service backend                      # JSON request lines; no tracebacks
```

Open `https://<frontend-domain>/en/login` and sign in as the administrator. In the dashboard, each
service's settings show its region as EU West (Amsterdam).

### 9. Turn on database backups

Dashboard → **Postgres** → **Backups**: add a daily and a weekly schedule. Backup schedules for
managed databases are not part of IaC.

## Day-2 operations

| Task | How |
|---|---|
| Ship code | Merge to `master`. Railway rebuilds only the service whose watch path changed (`/backend/**` or `/frontend/**`), once CI is green, running migrations before the new backend takes traffic. |
| Change infrastructure | Edit `.railway/railway.ts` in a PR. CI runs `npm run verify`; with [CI apply](#apply-from-ci) on, it also posts the plan and applies it on merge. Otherwise `railway config plan && railway config apply` locally. |
| Add a variable | Add it to `railway.ts` — a literal, or `preserve()` plus `railway variable set` for a secret. |
| Rotate `SECRET_KEY` | Step 4's command without `--skip-deploys`. All sessions end; everyone signs in again. |
| Roll back a bad deploy | Dashboard → service → **Deployments** → previous deployment → **Rollback**. Migrations are not rolled back: if the bad deploy migrated, run the `alembic downgrade` for that revision via `railway ssh` first. |
| Logs | `railway logs --service backend` (or `frontend`, `Postgres`). |
| Reset an admin's password | Step 7 again with their username. |
| `psql` / `pg_dump` | `railway connect Postgres`. Railway's Postgres also exposes a password-protected TLS proxy, which the IaC engine keeps. |
| Demo data on a non-production environment | `railway ssh --service backend -- python scripts/seed_fake_data.py` — only where the README's demo passwords being known is acceptable. Never in production. |

### Custom domains

Set `WEB_DOMAIN` and/or `API_DOMAIN` at the top of `railway.ts` and apply. That attaches the domains
and repoints `NEXT_PUBLIC_API_URL` and `CORS_ORIGINS` (the generated frontend domain stays allowed
during the DNS cutover). Then:

Create the DNS records Railway shows for each domain (service → **Settings → Networking**), then,
if `API_DOMAIN` changed, rebuild the frontend — the API URL is baked in at build time:

```bash
railway redeploy --service frontend --from-source --yes
```

### Apply from CI

`.github/workflows/railway-iac.yml` always validates `.railway/`. Planning and applying stay off
until you opt in:

1. Railway → project **Settings → Tokens** → create a project token for `production`.
2. GitHub → **Settings → Secrets and variables → Actions**: secret `RAILWAY_TOKEN` = that token;
   variable `RAILWAY_IAC_ENABLED` = `true`.

From then on every PR touching `.railway/` gets a plan comment, and merging applies exactly that
plan. **Destructive changes are refused on merge** (`confirm-destructive: "false"`) — deleting a
service, the database or a variable has to be applied from a terminal, deliberately.

## EU data residency

Pinning covers where the services run and where the database volume lives, and `check.ts` keeps it
that way. It does not by itself make every data flow EU-only:

- **OCR.** With `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` set, receiving documents uploaded on the
  Receiving page are sent to Google's and Anthropic's APIs. Check those providers' data-processing
  terms and regional options against your obligations, or leave the keys unset.
- **The platform itself.** Railway's builds, logs and edge network are Railway's own services;
  review [Railway's DPA](https://railway.com/legal/dpa) for what it commits to.

## Troubleshooting

| Symptom | Cause → fix |
|---|---|
| Backend deploy fails: `APP_ENV=production requires SECRET_KEY…` | `SECRET_KEY` unset or too short → [step 4](#4-set-the-secrets). |
| Backend deploy fails in **pre-deploy** | Migration failed; the deployment's logs (dashboard, or `railway logs --service backend --deployment`) show alembic's error. On a first deploy, Postgres was usually still starting → redeploy. |
| Login does nothing; the browser console shows requests to `https:///api/v1/…` or `localhost:8000` | The frontend was built before the backend domain existed → `railway redeploy --service frontend --from-source --yes`. |
| Every API call CORS-blocked | `CORS_ORIGINS` resolved before the frontend had a domain → `railway redeploy --service backend --yes`. |
| Login fails with a 500 from `/api/auth/login` | The auth proxy can't reach `BACKEND_URL` → check the backend is healthy; `railway logs --service frontend`. |
| `railway config plan` wants to delete a variable | It was set in the dashboard but isn't in `railway.ts` → add it there (or `preserve()` it). |
| `The Railway TypeScript SDK is not installed` | `npm ci --prefix .railway`. |
