"""
Tests for T06 — User Management API.
Expected: 16 passed, 0 failed.
All tests run without a live database connection.
"""
from datetime import datetime
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.user import Role, User, UserRoleAssignment
from app.schemas.auth import TokenUser
from app.schemas.user import (
    PaginatedUsers,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.services import user_service

BASE_URL = "http://test"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_db_user(user_id: int = 1, status: str = "active") -> User:
    u = User()
    u.id = user_id
    u.username = "testuser"
    u.full_name = "Test User"
    u.preferred_language = "en"
    u.status = status
    u.password_hash = hash_password("password123")
    u.created_at = datetime(2026, 1, 1, 12, 0, 0)
    return u


def _make_auth_session(user=None, roles=None, privileges=None):
    """
    Mock AsyncSession satisfying the 3 require_privilege queries:
      n=1 — scalar_one_or_none() → User
      n=2 — fetchall() → roles
      n=3 — fetchall() → privileges
    """
    roles = roles or ["company_admin"]
    privileges = privileges or ["users.manage"]
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
    session.refresh = AsyncMock()
    session.flush = AsyncMock()
    return session


def _override(session):
    async def _dep():
        yield session
    return _dep


def _auth_header(user_id: int = 1) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id=user_id)}"}


def _make_user_response(user_id: int = 1) -> UserResponse:
    return UserResponse(
        id=user_id, username="testuser", full_name="Test User",
        roles=["company_admin"], preferred_language="en", status="active",
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )


def _make_paginated() -> PaginatedUsers:
    return PaginatedUsers(total=1, page=1, page_size=20, results=[_make_user_response()])


# ---------------------------------------------------------------------------
# Service DB helpers
# ---------------------------------------------------------------------------

def _make_service_db():
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    return db


def _r_scalar(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _r_fetchall(rows):
    r = MagicMock()
    r.fetchall.return_value = rows
    return r


def _r_scalar_count(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _r_scalars_all(items):
    r = MagicMock()
    sc = MagicMock()
    sc.all.return_value = items
    r.scalars.return_value = sc
    return r


# ===========================================================================
# HTTP tests — cover all 7 router handlers (service mocked)
# ===========================================================================

@pytest.mark.asyncio
async def test_list_users_no_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
        resp = await c.get("/api/v1/users")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_list_users_success():
    session = _make_auth_session(user=_make_db_user())
    app.dependency_overrides[get_db] = _override(session)
    try:
        with patch("app.services.user_service.list_users", new_callable=AsyncMock) as mock:
            mock.return_value = _make_paginated()
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.get("/api/v1/users", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_create_user_returns_201():
    session = _make_auth_session(user=_make_db_user())
    app.dependency_overrides[get_db] = _override(session)
    try:
        with patch("app.services.user_service.create_user", new_callable=AsyncMock) as mock:
            mock.return_value = _make_user_response(user_id=5)
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.post(
                    "/api/v1/users",
                    json={"username": "new", "full_name": "New", "password": "p", "role_ids": []},
                    headers=_auth_header(),
                )
        assert resp.status_code == 201
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_update_me_success():
    session = _make_auth_session(user=_make_db_user(), privileges=["inventory.view"])
    app.dependency_overrides[get_db] = _override(session)
    try:
        with patch("app.services.user_service.update_me", new_callable=AsyncMock) as mock:
            mock.return_value = UserResponse(
                id=1, username="testuser", full_name="Test User",
                roles=[], preferred_language="es", status="active",
                created_at=datetime(2026, 1, 1),
            )
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.patch(
                    "/api/v1/users/me",
                    json={"preferred_language": "es"},
                    headers=_auth_header(),
                )
        assert resp.status_code == 200
        assert resp.json()["preferred_language"] == "es"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_user_not_found_http():
    session = _make_auth_session(user=_make_db_user())
    app.dependency_overrides[get_db] = _override(session)
    try:
        with patch("app.services.user_service.get_user", new_callable=AsyncMock) as mock:
            mock.side_effect = HTTPException(status_code=404, detail="User not found")
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.get("/api/v1/users/999", headers=_auth_header())
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_update_user_last_admin_http():
    session = _make_auth_session(user=_make_db_user())
    app.dependency_overrides[get_db] = _override(session)
    try:
        with patch("app.services.user_service.update_user", new_callable=AsyncMock) as mock:
            mock.side_effect = HTTPException(409, detail="Cannot deactivate the last admin")
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.patch(
                    "/api/v1/users/1", json={"status": "inactive"}, headers=_auth_header()
                )
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_change_password_http():
    session = _make_auth_session(user=_make_db_user())
    app.dependency_overrides[get_db] = _override(session)
    try:
        with patch("app.services.user_service.change_password", new_callable=AsyncMock) as mock:
            mock.return_value = {"detail": "Password changed successfully"}
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.post(
                    "/api/v1/users/1/change-password",
                    json={"new_password": "newpass"},
                    headers=_auth_header(),
                )
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_replace_roles_http():
    session = _make_auth_session(user=_make_db_user())
    app.dependency_overrides[get_db] = _override(session)
    try:
        with patch("app.services.user_service.replace_roles", new_callable=AsyncMock) as mock:
            mock.return_value = _make_user_response()
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.post(
                    "/api/v1/users/1/roles", json={"role_ids": [1]}, headers=_auth_header()
                )
        assert resp.status_code == 200
    finally:
        app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# Service unit tests — directly exercise service logic with mocked DB
# ===========================================================================

@pytest.mark.asyncio
async def test_svc_list_users():
    user = _make_db_user()
    db = _make_service_db()
    # count, main users, then one batched roles query (uid, role_name) tuples
    db.execute.side_effect = [
        _r_scalar_count(1),
        _r_scalars_all([user]),
        _r_fetchall([(1, "company_admin")]),
    ]
    result = await user_service.list_users(db, 1, 20, None, None)
    assert result.total == 1
    assert result.results[0].username == "testuser"


@pytest.mark.asyncio
async def test_svc_get_user_success():
    user = _make_db_user()
    db = _make_service_db()
    # _get_user_or_404, then _fetch_roles_for_users
    db.execute.side_effect = [
        _r_scalar(user),
        _r_fetchall([(1, "company_admin")]),
    ]
    result = await user_service.get_user(db, 1)
    assert result.id == 1
    assert result.username == "testuser"


@pytest.mark.asyncio
async def test_svc_create_user_success():
    db = _make_service_db()
    added_user: list = []

    def _on_add(obj):
        if isinstance(obj, User):
            added_user.append(obj)

    db.add = MagicMock(side_effect=_on_add)

    async def _on_flush():
        for u in added_user:
            u.id = 7
            u.created_at = datetime(2026, 1, 1)

    db.flush = _on_flush
    # duplicate check (None = no conflict); role_ids=[] so _validate_role_ids skips;
    # after commit: _fetch_roles_for_users
    db.execute.side_effect = [
        _r_scalar(None),
        _r_fetchall([(7, "company_admin")]),
    ]
    data = UserCreate(
        username="alice", full_name="Alice", password="pass123",
        preferred_language="en", role_ids=[],
    )
    result = await user_service.create_user(db, data, actor_id=1)
    assert result.username == "alice"


@pytest.mark.asyncio
async def test_svc_update_user_success():
    user = _make_db_user()
    db = _make_service_db()
    # _get_user_or_404, then _fetch_roles_for_users after commit
    db.execute.side_effect = [
        _r_scalar(user),
        _r_fetchall([(1, "company_admin")]),
    ]
    data = UserUpdate(full_name="Changed Name")
    result = await user_service.update_user(db, 1, data, actor_id=1)
    assert result.id == 1


@pytest.mark.asyncio
async def test_svc_update_user_last_admin():
    user = _make_db_user()
    admin_role = Role()
    admin_role.id = 1
    admin_role.role_name = "company_admin"
    ura = UserRoleAssignment()
    ura.user_id = 1
    ura.role_id = 1
    db = _make_service_db()
    db.execute.side_effect = [
        _r_scalar(user),         # _get_user_or_404
        _r_scalar(admin_role),   # company_admin role lookup
        _r_scalar_count(1),      # count active admins
        _r_scalar(ura),          # user IS the last admin
    ]
    data = UserUpdate(status="inactive")
    with pytest.raises(HTTPException) as exc_info:
        await user_service.update_user(db, 1, data, actor_id=1)
    assert exc_info.value.status_code == 409
    assert "last admin" in exc_info.value.detail


@pytest.mark.asyncio
async def test_svc_update_me():
    user = _make_db_user()
    db = _make_service_db()
    db.execute.side_effect = [
        _r_scalar(user),
        _r_fetchall([(1, "company_admin")]),
    ]
    result = await user_service.update_me(db, 1, "es")
    assert result.preferred_language == "es"


@pytest.mark.asyncio
async def test_svc_change_password_admin_bypass():
    user = _make_db_user()
    db = _make_service_db()
    db.execute.side_effect = [_r_scalar(user)]
    actor = TokenUser(
        user_id=99, full_name="Admin", roles=["company_admin"],
        preferred_language="en", effective_privileges=["users.manage"],
    )
    result = await user_service.change_password(db, 1, None, "newpass", actor)
    assert result["detail"] == "Password changed successfully"


@pytest.mark.asyncio
async def test_svc_replace_roles():
    user = _make_db_user()
    op_role = Role()
    op_role.id = 2
    op_role.role_name = "operator"
    db = _make_service_db()
    db.execute.side_effect = [
        _r_scalar(user),                    # _get_user_or_404
        _r_scalars_all([2]),                # _validate_role_ids: found role ids
        MagicMock(),                        # DELETE UserRoleAssignment
        _r_fetchall([(1, "operator")]),     # _fetch_roles_for_users after commit
    ]
    result = await user_service.replace_roles(db, 1, [2], actor_id=1)
    assert "operator" in result.roles


# ---------------------------------------------------------------------------
# T19 — production_line round-trip (schema + service)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_svc_create_user_persists_production_line():
    """An operator created with a production line keeps it on the ORM object."""
    db = _make_service_db()
    added_user: list = []

    def _on_add(obj):
        if isinstance(obj, User):
            added_user.append(obj)

    db.add = MagicMock(side_effect=_on_add)

    async def _on_flush():
        for u in added_user:
            u.id = 8
            u.created_at = datetime(2026, 1, 1)

    db.flush = _on_flush
    db.execute.side_effect = [
        _r_scalar(None),                          # no duplicate username
        _r_fetchall([(8, "machine_operator")]),   # _fetch_roles_for_users
    ]
    data = UserCreate(
        username="op7", full_name="Operator Seven", password="pass123",
        preferred_language="en", production_line="LINE-A", role_ids=[],
    )
    result = await user_service.create_user(db, data, actor_id=1)

    assert added_user[0].production_line == "LINE-A"
    assert result.production_line == "LINE-A"


@pytest.mark.asyncio
async def test_svc_update_user_sets_production_line():
    user = _make_db_user()
    user.production_line = None
    db = _make_service_db()
    db.execute.side_effect = [
        _r_scalar(user),
        _r_fetchall([(1, "machine_operator")]),
    ]
    result = await user_service.update_user(
        db, 1, UserUpdate(production_line="LINE-B"), actor_id=1
    )
    assert user.production_line == "LINE-B"
    assert result.production_line == "LINE-B"


@pytest.mark.asyncio
async def test_svc_update_user_non_last_admin_deactivates():
    """Deactivating an admin while another active admin remains succeeds."""
    user = _make_db_user()
    admin_role = Role()
    admin_role.id = 1
    admin_role.role_name = "company_admin"
    ura = UserRoleAssignment()
    ura.user_id = 1
    ura.role_id = 1
    db = _make_service_db()
    db.execute.side_effect = [
        _r_scalar(user),          # _get_user_or_404
        _r_scalar(admin_role),    # company_admin role lookup
        _r_scalar_count(2),       # two active admins — guard must not fire
        _r_scalar(ura),
        _r_fetchall([(1, "company_admin")]),
    ]
    result = await user_service.update_user(
        db, 1, UserUpdate(status="inactive"), actor_id=1
    )
    assert result.status == "inactive"
