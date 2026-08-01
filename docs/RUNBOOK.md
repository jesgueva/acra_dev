# Runbook

Operational reference for bringing the containerized stack (ACR-42 / A10-1) up, down, and back up
again — the packaging shape, the exact order services come up in, and the commands for the day-2
actions the README doesn't have room for. See [`README.md`](../README.md) for the quickstart and
[`docs/architecture.md`](architecture.md) for how this maps onto the system design.

## Packaging diagram

Two images (`acra-backend:local` is built once and reused by both the one-shot `migrate` job and the
long-running `backend` service; `acra-frontend:local` is separate), one named volume, four service
containers. Edges are `docker-compose.yml`'s `depends_on` conditions — nothing starts before its
condition is met.

```
┌──────────────┐
│ acra-postgres│  postgres:15, healthcheck: pg_isready
│  (volume:    │
│  acra-       │
│  postgres-   │
│  data)       │
└──────┬───────┘
       │ service_healthy
       ▼
┌──────────────┐   image: acra-backend:local
│ acra-migrate │   command: alembic upgrade head
│ (one-shot)   │   exits 0 on success; healthcheck disabled (it's not a server)
└──────┬───────┘
       │ service_completed_successfully
       ▼
┌──────────────┐   image: acra-backend:local
│ acra-backend │   uvicorn app.main:app, healthcheck: curl /health
└──────┬───────┘
       │ service_healthy
       ▼
┌──────────────┐   image: acra-frontend:local
│ acra-frontend│   Next.js standalone server, healthcheck: curl /
└──────────────┘

┌──────────────┐   image: acra-backend:local        profile: seed (opt-in only,
│ seed         │   command: python scripts/seed_fake_data.py   no container_name
│ (one-shot)   │   depends_on: db healthy, migrate completed_successfully   override)
└──────────────┘
```

`db` has no upstream dependency — it's the only service that starts unconditionally. Every other
service waits on a `condition:`, so a `docker compose up -d` genuinely serializes the correct order
rather than merely starting containers in file order.

## Bring-up

```bash
docker compose up -d --build      # Postgres → migrate → backend → frontend
docker compose ps                 # confirm all four are Up/healthy
```

Load demo data (opt-in — never runs on a plain `up`):

```bash
docker compose --profile seed run --rm seed
```

## Health checks

```bash
curl -i http://localhost:8000/health     # backend — expect 200 {"status":"ok"}
curl -i http://localhost:3000            # frontend — expect 200
docker compose ps                        # all services should read "healthy", not just "Up"
```

## Logs

```bash
docker compose logs -f backend        # follow one service
docker compose logs migrate           # one-shot job — check this first if backend never starts
```

## Teardown

```bash
docker compose down       # stop, keep the Postgres volume (data survives)
docker compose down -v    # stop and wipe the Postgres volume (clean-slate reset)
```

## Running multiple stacks side by side

Every host port and container name is overridable, because this repo is routinely checked out into
several worktrees at once:

```bash
ACRA_DB_PORT=5442 ACRA_BACKEND_PORT=8042 ACRA_FRONTEND_PORT=3042 \
  docker compose -p acr42 up -d --build
```

`-p <name>` namespaces the network and volume; the `ACRA_*_PORT` variables namespace the published
ports. Changing `ACRA_BACKEND_PORT` requires `--build`, not just a restart — see
[Troubleshooting](../README.md#troubleshooting) in the README.
