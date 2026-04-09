"""
Tests for T12 — Audit Log API.
Expected: 4 passed, 0 failed.
All tests run without a live database connection.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.audit import AuditLog
from app.models.user import User

BASE_URL = "http://test"
PRIVS_AUDIT = ["audit.view"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user() -> User:
    u = User()
    u.id = 1
    u.username = "admin"
    u.full_name = "Admin User"
    u.preferred_language = "en"
    u.status = "active"
    u.production_line = None
    u.password_hash = hash_password("password123")
    return u


def _make_log(
    id: int = 1,
    user_id: int = 1,
    action: str = "login",
    entity_type: str = "User",
    entity_id: int = 1,
) -> AuditLog:
    log = AuditLog()
    log.id = id
    log.user_id = user_id
    log.action = action
    log.entity_type = entity_type
    log.entity_id = entity_id
    log.details = None
    log.timestamp = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
    return log


def _make_session(user, roles, privileges, service_handlers=None):
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
    session.delete = AsyncMock()
    return session


def _override(session):
    async def _dep():
        yield session
    return _dep


# ---------------------------------------------------------------------------
# Test 1 — GET /audit-logs returns 200 with paginated results
# ---------------------------------------------------------------------------
async def test_list_audit_logs_returns_200():
    user = _make_user()
    log = _make_log()

    def h_count(r): r.scalar.return_value = 1
    def h_rows(r): r.scalars.return_value.all.return_value = [log]

    session = _make_session(user, ["company_admin"], PRIVS_AUDIT, [h_count, h_rows])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/audit-logs",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert len(body["results"]) == 1
        assert body["results"][0]["action"] == "login"
        assert body["results"][0]["entity_type"] == "User"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 2 — No auth returns 401/403
# ---------------------------------------------------------------------------
async def test_list_audit_logs_no_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get("/api/v1/audit-logs")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Test 3 — Filters are forwarded (action, entity_type, user_id)
# ---------------------------------------------------------------------------
async def test_list_audit_logs_with_filters():
    user = _make_user()
    log = _make_log(action="logout", entity_type="Session")

    def h_count(r): r.scalar.return_value = 1
    def h_rows(r): r.scalars.return_value.all.return_value = [log]

    session = _make_session(user, ["company_admin"], PRIVS_AUDIT, [h_count, h_rows])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/audit-logs",
                params={"action": "logout", "entity_type": "Session", "user_id": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["results"][0]["action"] == "logout"
        assert body["results"][0]["entity_type"] == "Session"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 4 — Missing audit.view privilege returns 403
# ---------------------------------------------------------------------------
async def test_list_audit_logs_missing_privilege():
    user = _make_user()

    session = _make_session(user, ["receiving_clerk"], ["deliveries.create"])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/audit-logs",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)
