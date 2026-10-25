# .railway — production infrastructure as code

ACRA MES on [Railway](https://docs.railway.com/infrastructure-as-code), EU West (Amsterdam). The
runbook — first-time setup, secrets, first admin, day-2 operations — is
[`docs/DEPLOY_RAILWAY.md`](../docs/DEPLOY_RAILWAY.md).

| File | Role |
|---|---|
| `railway.ts` | The project: Postgres 15, `backend`, `frontend`, all pinned to `europe-west4-drams3a`. Evaluated by the Railway CLI. |
| `check.ts` | Offline invariants: region pinning, no literal secrets, backend URL wiring, PORT vs Dockerfile `EXPOSE`. |
| `package.json` / `package-lock.json` | Pins the Railway SDK (`railway`) and TypeScript. |
| `tsconfig.json` | Typecheck only — the CLI runs `railway.ts` with type stripping, which ignores types. |

```bash
npm ci --prefix .railway            # once
npm --prefix .railway run verify    # typecheck + check.ts — no Railway account needed
railway config plan                 # diff against the linked project (read-only)
railway config apply                # apply after confirmation
```

`railway.ts` is the single source of truth for the environment: anything missing from it — a
service, a variable added in the dashboard — is deleted on the next apply.
