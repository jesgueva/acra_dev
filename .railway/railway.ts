// ACRA MES on Railway — the whole stack, pinned to the EU.
//
// Railway Infrastructure as Code (https://docs.railway.com/infrastructure-as-code), evaluated by
// the Railway CLI. This one file is the source of truth for the project: a resource or variable
// missing from it is DELETED on the next apply, so add things here rather than in the dashboard.
//
//   npm ci --prefix .railway          install the pinned SDK (once)
//   npm --prefix .railway run verify  offline: typecheck + the invariants in check.ts
//   railway config plan               preview against the linked project (read-only)
//   railway config apply              apply after confirmation
//
// It mirrors docker-compose.yml: Postgres → backend (migrations run as its pre-deploy step, in
// place of compose's one-shot `migrate`) → frontend. First-time setup, the secrets this file
// deliberately does not contain, and day-2 operations are in docs/DEPLOY_RAILWAY.md.

import { database, defineRailway, github, preserve, project, service } from "railway/iac";

// EU West (Amsterdam). Every service AND the database volume live here — that is the data-residency
// requirement, so check.ts fails if any resource names another region or none at all.
// Region identifiers: https://docs.railway.com/deployments/regions
const EU_WEST = "europe-west4-drams3a";

const REPO = "jesgueva/acra_dev";
const BRANCH = "master";

// Railway's TLS-enabled Postgres image, held at the major docker-compose.yml and CI test against
// (postgres:15). The `postgres()` helper would pick 18 — a major nothing in this repo runs. Bump all
// three together; backend/tests/test_packaging.py fails the build if they drift.
const POSTGRES_IMAGE = "ghcr.io/railwayapp-templates/postgres-ssl:15";

// What the images listen on (EXPOSE in backend/Dockerfile and frontend/Dockerfile). Setting PORT
// explicitly tells Railway which port to route and health-check; check.ts asserts these match.
const BACKEND_PORT = 8000;
const FRONTEND_PORT = 3000;

// Optional custom domains. Leave null to serve on the generated *.up.railway.app domains. Setting
// one attaches it below AND repoints NEXT_PUBLIC_API_URL / CORS_ORIGINS at it — and since
// NEXT_PUBLIC_API_URL is baked in at build time, the frontend rebuilds on the next deploy.
const WEB_DOMAIN: string | null = null; // e.g. "mes.example.com"
const API_DOMAIN: string | null = null; // e.g. "api.mes.example.com"

const BACKEND = "backend";
const FRONTEND = "frontend";

/**
 * `${{service.VARIABLE}}` — a Railway reference variable, written out so it can sit inside a larger
 * value (a URL). Railway resolves it when the service builds and deploys.
 */
function reference(serviceName: string, variable: string): string {
  return `\${{${serviceName}.${variable}}}`;
}

export default defineRailway(() => {
  const db = database("Postgres", "postgres", {
    image: POSTGRES_IMAGE,
    output: "DATABASE_URL",
    defaultMountPath: "/var/lib/postgresql/data",
    region: EU_WEST,
  });

  // Railway's own DATABASE_URL is `postgresql://…`; the app needs the asyncpg dialect, so assemble
  // the DSN from the parts. PGHOST is the private-network hostname — the DB is never reached over
  // the public internet by the app.
  const databaseUrl =
    `postgresql+asyncpg://${reference(db.name, "PGUSER")}:${reference(db.name, "PGPASSWORD")}` +
    `@${reference(db.name, "PGHOST")}:${reference(db.name, "PGPORT")}/${reference(db.name, "PGDATABASE")}`;

  const webHost = reference(FRONTEND, "RAILWAY_PUBLIC_DOMAIN");
  const apiHost = API_DOMAIN ?? reference(BACKEND, "RAILWAY_PUBLIC_DOMAIN");
  // Keep the generated domain allowed after adding a custom one, so the *.up.railway.app URL keeps
  // working during a DNS cutover.
  const corsOrigins = [WEB_DOMAIN, webHost]
    .filter((host) => host !== null)
    .map((host) => `https://${host}`);

  const backend = service(BACKEND, {
    // checkSuites = Railway's "Wait for CI": a push to master deploys only once its GitHub Actions
    // runs pass, so a red build never reaches production.
    source: github(REPO, { branch: BRANCH, rootDirectory: "backend", checkSuites: true }),
    // Patterns are matched from the repo root even with rootDirectory set.
    build: { builder: "DOCKERFILE", watchPatterns: ["/backend/**"] },
    // Replaces compose's `migrate` job: runs in a throwaway container from the same image, on the
    // private network, before the new deployment takes traffic. A failed migration fails the
    // deploy and the previous one keeps serving. The timeout turns a migration stuck on a lock into
    // a failed deploy instead of one that hangs forever.
    preDeploy: "alembic upgrade head",
    healthcheck: "/health",
    healthcheckTimeout: 120,
    replicas: { [EU_WEST]: 1 },
    domains: API_DOMAIN ? [{ domain: API_DOMAIN, port: BACKEND_PORT }] : undefined,
    deploy: {
      preDeployTimeoutSeconds: 600,
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 10,
    },
    env: {
      PORT: String(BACKEND_PORT),
      DATABASE_URL: databaseUrl,
      // Fails closed: with APP_ENV=production the API refuses to boot on a missing, default or short
      // SECRET_KEY rather than signing JWTs with the public default in app/core/config.py.
      APP_ENV: "production",
      ALGORITHM: "HS256",
      ACCESS_TOKEN_EXPIRE_MINUTES: "480",
      CORS_ORIGINS: corsOrigins.join(","),
      LOG_FORMAT: "json",
      // TLS ends at Railway's edge. Without this uvicorn ignores X-Forwarded-Proto, so redirects
      // FastAPI generates (e.g. trailing-slash) point at http:// and the browser blocks them as
      // mixed content.
      FORWARDED_ALLOW_IPS: "*",
      OCR_MOCK_MODE: "false",
      // Secrets: declared so an apply never deletes them, but the values are set out-of-band and
      // never appear in this file — see docs/DEPLOY_RAILWAY.md "Secrets".
      SECRET_KEY: preserve(),
      ANTHROPIC_API_KEY: preserve(),
    },
  });

  const frontend = service(FRONTEND, {
    source: github(REPO, { branch: BRANCH, rootDirectory: "frontend", checkSuites: true }),
    build: { builder: "DOCKERFILE", watchPatterns: ["/frontend/**"] },
    healthcheck: "/en/login",
    healthcheckTimeout: 120,
    replicas: { [EU_WEST]: 1 },
    domains: WEB_DOMAIN ? [{ domain: WEB_DOMAIN, port: FRONTEND_PORT }] : undefined,
    deploy: {
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 10,
    },
    env: {
      PORT: String(FRONTEND_PORT),
      // The standalone Next server binds HOSTNAME; pin it so a platform-injected container hostname
      // can never make it listen on the wrong interface.
      HOSTNAME: "0.0.0.0",
      // The two backend URLs — the gotcha in CLAUDE.md, now with Railway's names:
      //   NEXT_PUBLIC_API_URL  BUILD time (Railway passes service variables to the Dockerfile's
      //                        ARG), inlined into the browser bundle → the PUBLIC https domain.
      //   BACKEND_URL          RUNTIME, server-side auth proxy → the PRIVATE network hostname.
      // check.ts fails if either is pointed the wrong way.
      NEXT_PUBLIC_API_URL: `https://${apiHost}`,
      BACKEND_URL: `http://${reference(BACKEND, "RAILWAY_PRIVATE_DOMAIN")}:${BACKEND_PORT}`,
    },
  });

  return project("acra-mes", {
    resources: [db, backend, frontend],
  });
});
