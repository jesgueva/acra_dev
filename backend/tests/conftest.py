import itertools
from unittest.mock import AsyncMock, MagicMock

from app.core.security import hash_password
from app.models.user import User


def _make_user(
    password: str = "password123",
    status: str = "active",
    production_line: str | None = None,
) -> User:
    u = User()
    u.id = 1
    u.username = "testuser"
    u.full_name = "Test User"
    u.preferred_language = "en"
    u.status = status
    u.production_line = production_line
    u.password_hash = hash_password(password)
    return u


def _make_session(user, roles, privileges, service_handlers=None):
    """
    Build a mock AsyncSession.

    - Execute calls 0-2: RBAC (user lookup, roles, privileges)
    - Execute calls 3+: service_handlers[i](result_mock) for sequential service queries
    """
    service_handlers = service_handlers or []
    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        n = call_no["n"]
        call_no["n"] += 1
        if n == 0:
            result.scalar_one_or_none.return_value = user
        elif n == 1:
            result.fetchall.return_value = [(r,) for r in roles]
        elif n == 2:
            result.fetchall.return_value = [(p,) for p in privileges]
        else:
            svc_idx = n - 3
            if svc_idx < len(service_handlers):
                service_handlers[svc_idx](result)
        return result

    session.execute = _execute
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    return session


def _make_service_session(handlers=None, assign_ids=False, created_at=None):
    """
    Build a mock AsyncSession for calling a service function **directly**.

    Unlike `_make_session`, no `require_privilege` dependency runs, so there are no RBAC queries to
    skip: `handlers[0]` answers the service's first `execute`.

    `assign_ids=True` makes `flush()` fill in what the database would — a primary key, and
    `created_at` for the `server_default` columns. A service that reads `obj.id` straight after a
    flush to stamp child rows cannot be exercised without it. Everything added is collected on
    `session.added` so a test can assert on what was written.
    """
    handlers = handlers or []
    session = AsyncMock()
    call_no = {"n": 0}
    added: list = []

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        n = call_no["n"]
        call_no["n"] += 1
        if n < len(handlers):
            handlers[n](result)
        return result

    session.execute = _execute
    session.added = added
    session.commit = AsyncMock()
    session.delete = AsyncMock()

    if assign_ids:
        next_id = itertools.count(1)

        async def _flush():
            for obj in added:
                if getattr(obj, "id", None) is None:
                    obj.id = next(next_id)
                if created_at is not None and getattr(obj, "created_at", None) is None:
                    obj.created_at = created_at

        session.add = added.append
        session.flush = _flush
    else:
        session.add = MagicMock(side_effect=added.append)
        session.flush = AsyncMock()

    return session


def _override(session):
    async def _dep():
        yield session
    return _dep


def _make_rbac_session(privileges=("deliveries.create", "deliveries.view")):
    """Mock AsyncSession satisfying the 3 RBAC execute() calls."""
    user = _make_user()
    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        call_no["n"] += 1
        n = call_no["n"]
        if n == 1:
            result.scalar_one_or_none.return_value = user
        elif n == 2:
            result.fetchall.return_value = [("receiving_clerk",)]
        else:
            result.fetchall.return_value = [(p,) for p in privileges]
        return result

    session.execute = _execute
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session
