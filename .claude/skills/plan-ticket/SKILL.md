---
name: plan-ticket
description: Explore the current ACRA MES codebase and write a review-ready implementation plan for a ticket (a Linear ID like ACR-29, or a described change) WITHOUT modifying code. Use this before implementing anything — the plan is reviewed and approved before any build work starts.
---

# Plan a ticket (explore → plan → stop for review)

You are planning ONE ticket. **Read-only.** Do not modify code, create a worktree/branch, run
servers, or install anything. Produce one plan file, then stop for the user's review.

The ticket to plan is the argument: a Linear identifier (`ACR-NN`) or a short description.

## 1. Get the ticket
- If given an `ACR-NN`: pull it with the Linear MCP (`get_issue`, includeRelations=true) to read
  the goal, acceptance criteria, refs, and `blockedBy`. Confirm its blockers are Done; if not,
  say so and ask whether to plan against the blocker's branch or wait.
- If given a description: treat that as the spec.

## 2. Orient
Read `CLAUDE.md` and `CONTRIBUTING.md` at the repo root first. They define the conventions
(router→service layering; shadcn/ui only; locale-prefixed links; RBAC 3-query test pattern via
`tests/conftest.py`; branches `ticket-NN/<slug>` → PR into `master`; ≥85% backend coverage).

## 3. Explore the current state (read-only)
- What already exists that this ticket touches: models, routers, services, schemas, Alembic
  migrations, frontend components. Cite `file:line`.
- The closest existing pattern to imitate.
- What is missing vs. the acceptance criteria.
- Schema/migration impact: the next sequential Alembic revision number and whether it must be
  reversible.

## 4. Write the plan
Write `plans/plan_ticket_NN.md` (repo root `plans/`) with:
- **Current state** — what exists today, with `file:line` references.
- **Change list** — exact files to CREATE and MODIFY, each with a one-line purpose.
- **Data / API** — new models, migration, endpoint contracts, RBAC privileges.
- **Test plan** — backend cases (happy + RBAC 403 + validation), frontend component tests, and
  the e2e flow to assert live.
- **Live verification** — the exact user flow to walk in the browser.
- **Risks / open questions** — anything ambiguous the user must decide before implementation.
- **Build order** — the ordered steps.

## 5. Stop
Return the plan path, a ~5-line summary, and any open questions. **Do not implement.** Wait for
the user to review and approve. When approved, the `implement-ticket` skill takes over.
