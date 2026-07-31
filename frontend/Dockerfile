# ACRA MES frontend — Next.js 16 production server (ACR-42 / A10-1).
#
# Node 24 matches .nvmrc / frontend/.nvmrc / engines.node; tests/test_packaging.py fails the build
# if those drift apart.
#
#   docker build -f frontend/Dockerfile -t acra-frontend frontend/
#
# ---------------------------------------------------------------------------------------------
# THE ONE THING TO GET RIGHT: there are two different backend URLs, and they are not interchangeable.
#
#   NEXT_PUBLIC_API_URL  is read by src/lib/api-client.ts and inlined into the BROWSER bundle at
#                        BUILD time. The browser runs on the host, outside the compose network, so
#                        this must be a host-reachable URL (http://localhost:8000) and must arrive
#                        as a build ARG. A runtime env var cannot change it — the value is already
#                        baked into the shipped JavaScript.
#
#   BACKEND_URL          is read at RUNTIME by the server-side auth proxy (app/api/auth/*). That
#                        code runs inside the container, so it uses the compose service name
#                        (http://backend:8000).
#
# Wire these the same way round and the stack still reports healthy while every login fails.
# scripts/compose-smoke.sh asserts both directions.
# ---------------------------------------------------------------------------------------------

# ----------------------------------------------------------------------------- dependencies
FROM node:24-alpine AS deps

WORKDIR /app

# npm ci needs both files and installs exactly what package-lock.json resolves.
COPY package.json package-lock.json ./
RUN npm ci

# ----------------------------------------------------------------------------- build
FROM node:24-alpine AS build

WORKDIR /app

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# This project has no public/ today — acra_logo.png is imported as a module
# (src/components/brand/AcraLogo.tsx) so the build emits it into .next/static. Create the directory
# anyway so the runtime COPY below is valid now and still correct the day someone adds a favicon or
# robots.txt, instead of failing the build or silently dropping the files.
RUN mkdir -p public

# ----------------------------------------------------------------------------- runtime
FROM node:24-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN apk add --no-cache curl \
    && addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# `output: "standalone"` (next.config.mjs) produces a server bundling only the traced runtime
# dependencies. public/ and .next/static/ are not included in that trace and must be copied
# alongside it, or the app serves HTML with every asset 404ing.
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=build --chown=nextjs:nodejs /app/public ./public

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:3000/en/login || exit 1

CMD ["node", "server.js"]
