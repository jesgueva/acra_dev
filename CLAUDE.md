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

## Frontend UI Conventions

- **Always use shadcn/ui components** for all UI elements — `Button`, `Input`, `Label`, `Card`, `Dialog`, etc. Never use raw `<button>`, `<input>`, or `<label>` HTML elements in pages or feature components.
- Add new shadcn/ui components via: `npx shadcn@latest add <component> -y` from `frontend/`
- Components live in `frontend/components/ui/`. Import as `@/components/ui/<component>`.
- Privilege constants live in `src/lib/privileges.ts` — always use `PRIVILEGES.*` instead of raw strings.

## Backend Testing Patterns

### Authenticated endpoint mocks
Every `require_privilege` dependency fires **exactly 3 DB queries** before any service logic runs:
- `n=0` — `scalar_one_or_none()` → User lookup
- `n=1` — `fetchall()` → roles
- `n=2` — `fetchall()` → privileges

Build mocks against this sequence. The canonical helper is `_make_session` in `tests/test_inventory.py`.

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
