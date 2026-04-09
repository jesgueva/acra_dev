from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.audit import AuditLog

from tests.conftest import _make_session, _make_user, _override

BASE_URL = "http://test"
PRIVS_AUDIT = ["audit.view"]


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


async def test_list_audit_logs_no_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get("/api/v1/audit-logs")
    assert resp.status_code in (401, 403)


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
