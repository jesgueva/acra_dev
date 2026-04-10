# ACRA MES — Project Memory

## Project Overview

ACRA Integrated Manufacturing Execution System (MES) — a monorepo with a FastAPI backend and Next.js 14 frontend.

## Repository Structure

```
acra_dev/
├── backend/          # FastAPI + SQLAlchemy + PostgreSQL
│   ├── app/
│   │   ├── main.py
│   │   ├── core/
│   │   ├── models/
│   │   ├── routers/
│   │   ├── schemas/
│   │   └── services/
│   ├── alembic/
│   ├── tests/
│   └── requirements.txt
├── frontend/         # Next.js 14 App Router + shadcn/ui
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── package.json
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
# Requires PostgreSQL running locally
# Create database: createdb acra_db
# Connection: postgresql://postgres:postgres@localhost:5432/acra_db
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

### Frontend (`frontend/.env.local`)

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy (async), Alembic, PostgreSQL, bcrypt, python-jose
- **Frontend:** Next.js 16 (App Router), TypeScript, Tailwind CSS v4, shadcn/ui (Nova preset, Radix), next-intl, Recharts
- **Testing:** pytest (backend), Playwright (E2E)

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
`alert` · `badge` · `button` · `card` · `dialog` · `input` · `label` · `select` · `separator` · `skeleton`

Add more with: `npx shadcn@latest add <component> -y` from `frontend/` (requires network access in sandbox).

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
