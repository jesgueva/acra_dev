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


def _override(session):
    async def _dep():
        yield session
    return _dep
