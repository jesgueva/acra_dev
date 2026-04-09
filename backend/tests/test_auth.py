"""
Tests for T05 — Authentication API.
Expected: 7 passed, 0 failed.
All tests run without a live database connection.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.user import User
from app.schemas.auth import TokenUser

BASE_URL = "http://test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(status: str = "active") -> User:
    u = User()
    u.id = 1
    u.username = "testuser"
    u.full_name = "Test User"
    u.preferred_language = "en"
    u.status = status
    u.password_hash = hash_password("password123")
    return u


def _make_session(user=None, roles=None, privileges=None):
    """
    Build a mock AsyncSession whose execute() returns appropriate results
    for the login endpoint's three sequential queries:
      1. User lookup  (scalar_one_or_none)
      2. Roles query  (fetchall)
      3. Privs query  (fetchall)
    """
    roles = roles or ["admin"]
    privileges = privileges or ["inventory.view"]

    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        call_no["n"] += 1
        n = call_no["n"]
        if n == 1:
            result.scalar_one_or_none.return_value = user
        elif n == 2:
            result.fetchall.return_value = [(r,) for r in roles]
        else:
            result.fetchall.return_value = [(p,) for p in privileges]
        return result

    session.execute = _execute
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


def _override(session):
    """Return a FastAPI dependency override (async generator) for get_db."""
    async def _dep():
        yield session
    return _dep


# ---------------------------------------------------------------------------
# Test 1 — Successful login returns 200 with access_token
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_login_success():
    session = _make_session(user=_make_user())
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "password123"},
            )
        assert resp.status_code == 200
        assert "access_token" in resp.json()
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 2 — Wrong password returns 401
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_login_wrong_password_returns_401():
    session = _make_session(user=_make_user())
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "wrongpassword"},
            )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 3 — Unknown user returns 401
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_login_unknown_user_returns_401():
    session = _make_session(user=None)
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "ghost", "password": "whatever"},
            )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 4 — Inactive user returns 403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_login_inactive_user_returns_403():
    session = _make_session(user=_make_user(status="inactive"))
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "password123"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 5 — Login response has correct shape
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_login_response_shape():
    session = _make_session(
        user=_make_user(),
        roles=["admin"],
        privileges=["inventory.view", "admin"],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "password123"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        u = body["user"]
        assert u["user_id"] == 1
        assert u["full_name"] == "Test User"
        assert "admin" in u["roles"]
        assert u["preferred_language"] == "en"
        assert "inventory.view" in u["effective_privileges"]
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 6 — Logout without token returns 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_logout_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Test 7 — Logout with valid JWT returns 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_logout_success():
    token = create_access_token(user_id=1)

    # The logout route depends on require_privilege("authenticated"), which
    # internally calls get_db to look up the user + roles + privs (3 queries).
    # Then the route handler itself calls write_audit + commit via the same session.
    user = _make_user()
    session = _make_session(user=user, roles=["admin"], privileges=["admin"])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/auth/logout",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)
