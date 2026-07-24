---
name: implement-ticket
description: Implement an ACRA MES ticket from an APPROVED plan — create a git worktree + branch, build to the plan, write tests (pytest + Jest + Playwright), spin up the servers, verify the flow live in the browser, and open a PR. Use only after a plan-ticket plan has been reviewed and approved.
---

# Implement a ticket (from an approved plan → PR)

You are implementing ONE ticket end-to-end against an **approved** plan, from a fresh git worktree
to an open PR with passing tests and live browser verification. If no approved
`plans/plan_ticket_NN.md` exists, stop and ask the user to run `plan-ticket` first.

The argument is the ticket (`ACR-NN`) and/or the plan path. Read the plan first — it is your spec
of record. Repo root: `/Users/jesusesgueva/dev/acra/acra_dev`. Follow `CLAUDE.md` +
`CONTRIBUTING.md`.

## 0. Worktree & branch
- `git fetch origin`; then
  `git worktree add ../acra-worktrees/ticket-NN-<slug> -b ticket-NN/<slug> origin/master`.
- If a blocker's PR isn't merged yet, branch off that ticket's branch instead and note it in the PR.
- Do all work inside the worktree.

## 1. Environment
- `python -m venv .venv && pip install -r backend/requirements.txt`; `cd frontend && npm install`.
- Create `backend/.env` + `frontend/.env.local` from the `*.example` templates if missing. Never
  commit them; take real keys from the environment.
- `docker compose up -d db` (Postgres on host port **5433**); wait for the healthcheck.
- **Export before any db/backend command (KI-01):**
  `export DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/acra_db`
- `cd backend && alembic upgrade head`; add the reversible migration the plan specifies.

## 2. Implement
Build exactly the plan's change list, in its build order. Register any new router in
`backend/app/main.py` (the known merge point — keep it minimal).

## 3. Tests (required)
- Backend: `tests/test_<module>.py` using `_make_session/_make_user/_override` from
  `tests/conftest.py`; happy + RBAC 403 + validation; ≥85% line coverage on new `app.*` modules.
- Frontend: `*.test.tsx` (Jest + Testing Library) for the new components' key states.
- E2E: install if absent — `cd frontend && npm i -D @playwright/test && npx playwright install
  chromium` — and add `frontend/e2e/ticket-NN.spec.ts` for the plan's flow.

## 4. Gate (all green before PR)
Export `DATABASE_URL` first, then from the worktree:
- `cd backend && pytest tests/ -v --cov=app --cov-report=term-missing` (≥85%)
- `cd frontend && npx jest && npm run lint && npm run build`
- `./scripts/smoke-test.sh` (from repo root)
Fix and re-run until everything passes.

## 5. Live browser verification
- `./scripts/reset-db-and-seed.sh`
- Start backend: `uvicorn app.main:app --port 8000` (background).
- Start frontend for real — **NOT `next dev` (it panics, KI-02):**
  `cd frontend && npm run build && npm run start` (serves http://localhost:3000).
- `cd frontend && npx playwright test e2e/ticket-NN.spec.ts`.
- ALSO drive the running app with the Playwright MCP browser tools: log in, walk the plan's flow
  in order, confirm each step's expected result, and capture screenshots. Fix until it works live.
- Tear the servers down when done.

## 6. PR
- Small conventional commits (`feat:`, `test:`, `fix:`…).
- Rebase on latest `master`; if `backend/app/main.py` conflicts, KEEP ALL `include_router(...)` lines.
- `gh pr create --base master --head ticket-NN/<slug> --title "ticket-NN: <title>"
  --body "<summary + criteria checked + test results + screenshots + Closes ACR-NN>"`
- Add the PR link to the Linear ticket; delete `plans/plan_ticket_NN.md` (plan fulfilled).

## 7. Report
Return: worktree, branch, PR URL, backend/frontend/smoke/playwright results (pass-fail + numbers),
coverage %, screenshots, and PASS/FAIL. **Do not mark the ticket Done or merge the PR** — stop at
the open PR for human review.
