# Contributing & Engineering Conventions

This document is the engineering baseline for working in `acra_dev`: branch strategy, naming,
commit and tag conventions, the PR/CI flow, and where different kinds of artifacts live. It
formalizes the practices already used across the Phase 1 ticket history.

## Branch strategy

A lightweight trunk-based flow:

- **`master`** is the integration branch and is always intended to be runnable and green in CI.
- All work happens on a **short-lived feature branch** cut from `master`, merged back via PR.
- Branches are named **`ticket-NN/<short-slug>`**, e.g. `ticket-06/delivery-fk-refactor`,
  `ticket-21/sprint1-baseline`. `NN` is the ticket number; the slug is a few kebab-case words.
- Keep branches focused and short-lived; rebase or merge `master` in if they fall behind.
- Delete a feature branch after its PR merges.

| Branch | Purpose | Lifetime |
|---|---|---|
| `master` | Integration / release line | permanent |
| `ticket-NN/<slug>` | One ticket's work | until merged |

## Naming conventions

- **Branches:** `ticket-NN/<kebab-slug>`.
- **Python:** `snake_case` modules/functions, `PascalCase` classes. Backend layering is
  `router → service → repository`; routers never touch the DB directly (see
  [`docs/architecture.md`](docs/architecture.md) and [`CLAUDE.md`](CLAUDE.md)).
- **TypeScript/React:** `PascalCase` components and files (`NavSidebar.tsx`), `camelCase` helpers.
- **DB migrations:** Alembic revisions are sequential (`001_…` → `008_…`) with a descriptive slug.
- **Tests:** `tests/test_<module>.py` (backend), `*.test.tsx` (frontend).

## Commit messages

Conventional-commit style prefixes, imperative mood, scoped where useful:

```
feat: add shipment issue movements
fix: correct lot status check constraint
chore: extract documentation to separate acra_docs repo
docs: add architecture note and risk log
test: cover RBAC negative paths on inventory
```

Keep commits small and self-contained so history reads as a sequence of reviewable steps.

## Pull requests & CI

- Open a PR from your `ticket-NN/*` branch into `master`.
- CI (`.github/workflows/ci.yml`) must pass before merge:
  - **Backend:** install deps → apply migrations → `pytest` with an **85% coverage floor** on `app.*`.
  - **Frontend:** install → Jest test subset → `eslint` → `next build`.
- Prefer squash or a tidy merge so `master` history stays legible.

## Versioning & tags

- Releases use **annotated, semver-style tags**: `vMAJOR.MINOR.PATCH`, optionally with a
  descriptive suffix for milestone baselines (e.g. `v0.2.0-sprint1-baseline`).
- Tag from `master` at a known-good, smoke-tested commit; record the change set in
  [`CHANGELOG.md`](CHANGELOG.md).
- Create tags with a message and push them explicitly:
  ```bash
  git tag -a v0.2.0-sprint1-baseline -m "Sprint I engineering baseline"
  git push origin v0.2.0-sprint1-baseline
  ```
- A tag is a stable reference point for later comparison — never move or delete a published tag.

## Artifact storage conventions

What belongs in this repository vs. elsewhere:

| Artifact | Where it lives |
|---|---|
| Application code, migrations, seed scripts, tests | **in-repo** (`backend/`, `frontend/`, `scripts/`) |
| Engineering docs that track the code | **in-repo** (`README.md`, `CONTRIBUTING.md`, `docs/`, `CHANGELOG.md`, `KNOWN_ISSUES.md`, `CLAUDE.md`) |
| Secrets / credentials | **never committed** — local `.env` / `.env.local` only (templates: `*.example`) |
| Generated/build output | **git-ignored** (`.next/`, `__pycache__/`, `.venv/`, coverage) |
| Large binaries, datasets, exported reports, screenshots, course material | **out of this repo** (separate documentation archive) |
| Database data | the Docker volume; reproducible from migrations + `seed_fake_data.py`, never committed |

Rule of thumb: this repo holds **everything needed to build and run the system, and nothing
that can be regenerated or that must stay private.**

## Local setup & smoke test

See [`README.md`](README.md) for setup. Before opening a PR, run the smoke test:

```bash
./scripts/smoke-test.sh
```
