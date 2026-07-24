# ACRA MES — Project Memory

## Project Overview

ACRA Integrated Manufacturing Execution System (MES) — a monorepo with a FastAPI backend and Next.js 16 frontend.

## Repository Structure

```
acra_dev/
├── backend/          # FastAPI + SQLAlchemy + PostgreSQL
│   ├── app/
│   │   ├── main.py
│   │   ├── core/     # config, database, security (JWT/bcrypt), rbac, audit
│   │   ├── models/
│   │   ├── routers/
│   │   ├── schemas/
│   │   └── services/
│   ├── alembic/
│   ├── tests/
│   └── requirements.txt
├── frontend/         # Next.js 16 App Router + shadcn/ui
│   ├── app/          # routes, layouts, globals; app/api/auth/* proxies session to backend
│   ├── components/ui/  # shadcn primitives
│   ├── src/
│   │   ├── components/  # feature + layout components
│   │   ├── contexts/
│   │   └── lib/
│   ├── messages/     # next-intl (en.json, es.json)
│   └── package.json
├── docker-compose.yml  # Postgres on host port 5433 → container 5432
└── CLAUDE.md
```

## Run Commands

### Backend

```bash
# Install dependencies
cd backend && pip install -r requirements.txt

# Start dev server
cd backend && uvicorn app.main:app --reload --port 8000

# Run tests
cd backend && pytest tests/ -v

# Apply migrations
cd backend && alembic upgrade head
```

### Frontend

```bash
# Install dependencies
cd frontend && npm install

# Start dev server
cd frontend && npm run dev

# Build for production
cd frontend && npm run build
```

### Database

```bash
# Option A — local Postgres on default port
# Create database: createdb acra_db
# Connection: postgresql://postgres:postgres@localhost:5432/acra_db

# Option B — Docker Compose (repo root): Postgres is exposed on host port 5433
# Set DATABASE_URL / NEXT_PUBLIC_API_URL accordingly, e.g.:
# postgresql+asyncpg://postgres:postgres@localhost:5433/acra_db

# If 5433 is already taken, or you need a second worktree's DB up at the same time,
# override the port and container name instead of editing docker-compose.yml:
# ACRA_DB_PORT=5435 ACRA_DB_CONTAINER=acra-pg-mybranch COMPOSE_PROJECT_NAME=mybranch \
#   docker compose up -d
# (COMPOSE_PROJECT_NAME also namespaces the volume, so branches don't share data.)
```

## Environment Variables

### Backend (`backend/.env`)

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
GEMINI_API_KEY=your-gemini-api-key-here
ANTHROPIC_API_KEY=your-anthropic-api-key-here
```

Use port **5433** for `DATABASE_URL` when connecting to Postgres started via `docker compose up` in this repo.

### Frontend (`frontend/.env.local`)

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy (async), Alembic, PostgreSQL, bcrypt, python-jose
- **Frontend:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4, shadcn/ui (Nova preset, Radix), next-intl, TanStack React Query, Axios, Recharts
- **Testing:** pytest (backend, coverage floor 85% in CI), Jest + Testing Library (frontend; CI runs a subset plus full lint/build)

## Backend Core Modules (`app/core/`)

- **`config.py`** — `pydantic-settings` (`database_url`, JWT, API keys).
- **`database.py`** — async engine, `get_db`, `Base`.
- **`security.py`** — JWT create/verify, bcrypt hash/verify (not named `auth.py`).
- **`rbac.py`** — `HTTPBearer`; **`require_privilege(name)`** loads user, roles, privileges from DB (privilege `"authenticated"` skips the privilege check). **`require_any_privilege(*names)`** — caller has at least one of the listed privileges.
- **`audit.py`** — `write_audit` (caller commits).

## Frontend Design System

### Theme
- **Dark by default.** `next-themes` manages the `class` attribute on `<html>`. Default is `"dark"`; light mode is toggled via `ThemeToggle` in the sidebar.
- **Always use `resolvedTheme`** (not `theme`) from `useTheme()` — `theme` can return `"system"` and produce wrong labels/icons.
- Color tokens are CSS variables in `app/globals.css`. Do not use hardcoded Tailwind color classes (e.g. `bg-yellow-100`) for semantic UI — use `bg-destructive`, `text-muted-foreground`, etc.

### Fonts
- **Headings:** `Barlow` — loaded in `app/layout.tsx` as `--font-heading`. Use class `font-heading` on `h1`–`h6` or headings that need the display face.
- **Body/UI:** `IBM Plex Sans` — loaded as `--font-sans`. Applied globally via `html { font-family: var(--font-sans) }`.
- All `h1`–`h6` elements automatically receive `font-heading` via `@layer base` in `globals.css`.

### Installed shadcn/ui components
`alert` · `badge` · `button` · `card` · `combobox` · `command` · `dialog` · `input` · `input-group` · `label` · `popover` · `select` · `separator` · `skeleton` · `sonner` · `table` · `textarea`

Add more with: `npx shadcn@latest add <component> -y` from `frontend/` (requires network access in sandbox).

### App-specific UI
- **`CreatableCombobox`** — `src/components/ui/creatable-combobox.tsx` (searchable select with inline create for receiving/master data).

## Frontend UI Conventions

- **Always use shadcn/ui components** for all UI elements — `Button`, `Input`, `Label`, `Card`, `Alert`, `Badge`, `Separator`, etc. Never use raw `<button>`, `<input>`, or `<label>` HTML elements in pages or feature components.
- Use `Alert` + `AlertDescription` (from `@/components/ui/alert`) for all inline status/error messages — not custom `<div role="alert">`.
- Use `Badge` (from `@/components/ui/badge`) for status chips and reference tags — not custom `<span>` pills.
- Use `Separator` (from `@/components/ui/separator`) for visual dividers — not `border-b` on wrapper divs.
- Use `Skeleton` (from `@/components/ui/skeleton`) for loading states — not `<p>Loading…</p>`.
- Privilege constants live in `src/lib/privileges.ts` — always use `PRIVILEGES.*` instead of raw strings.

### Import path convention
- shadcn primitives: `@/components/ui/<component>` (lives at `frontend/components/ui/`)
- App components: `@/src/components/<domain>/<Component>` (lives at `frontend/src/components/`)
- Do not mix the two roots — use the path that matches the physical location.

### Locale routing
**Always prefix internal links with `/${locale}/`.** Use `useLocale()` from `next-intl` in client components:
```tsx
const locale = useLocale();
<Link href={`/${locale}/inventory`}>...</Link>
```
Bare paths like `href="/inventory"` will miss the locale segment and cause a redirect flash or 404.

### Auth and API
- Browser calls FastAPI at `NEXT_PUBLIC_API_URL` with Bearer tokens set on the shared Axios client (`src/lib/api-client.ts`).
- Session bootstrap uses Next.js route handlers under `app/api/auth/` (login/me/logout) to align cookies with the backend.

### Shared layout components
- **`PageHeader`** (`src/components/layout/PageHeader.tsx`) — use on every page for the title/description/actions row. Accepts `title`, `description?`, and `children` (action buttons slot).
- **`ModulePlaceholder`** (`src/components/layout/ModulePlaceholder.tsx`) — shared components for placeholder/coming-soon pages: `ComingSoonBadge`, `ModuleBanner`, `FeatureGrid`, `RequirementsBar`, `SectionLabel`.
- **`ThemeToggle`** (`src/components/layout/ThemeToggle.tsx`) — already wired into `NavSidebar`. Do not add a second theme toggle elsewhere.

## Backend Testing Patterns

### Authenticated endpoint mocks
Every `require_privilege` dependency fires **exactly 3 DB queries** before any service logic runs:
- `n=0` — `scalar_one_or_none()` → User lookup
- `n=1` — `fetchall()` → roles
- `n=2` — `fetchall()` → privileges

Build mocks against this sequence. The canonical helpers live in `tests/conftest.py` — import them rather than redefining:

```python
from tests.conftest import _make_session, _make_user, _override
```

- `_make_session(user, roles, privileges, service_handlers=[])` — wires the 3-query RBAC sequence; service queries start at index 3.
- `_make_user(password, status, production_line)` — returns an active `User` ORM stub.
- `_override(session)` — async generator for `app.dependency_overrides[get_db]`.

**Note:** `_make_rbac_session` in the same file uses **1-based** `execute` counting (`n == 1, 2, 3` for the same three RBAC steps). Use `_make_session` when you need 0-based indexing aligned with the doc above.

### Coverage
Use **dot notation** for `--cov` paths:
```bash
pytest tests/test_foo.py --cov=app.routers.foo --cov=app.services.foo_service --cov-report=term-missing
```

### SQLAlchemy AsyncSession
- `db.add(obj)` — sync, no `await`
- `db.delete(obj)` — async, needs `await`
- `db.commit()` / `db.execute()` — async, needs `await`

## Merge Notes

Each ticket adds its own router import + `app.include_router(...)` to `main.py`. Concurrent branches will conflict here — resolve manually at merge time by keeping all router registrations.
