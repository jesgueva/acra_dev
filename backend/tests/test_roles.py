"""
Tests for T19 — GET /api/v1/roles.

The User Management form needs role IDs to satisfy `UserCreate.role_ids`,
so this endpoint enumerates them. Runs without a live database.
"""
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import Role
from app.services import role_service

from tests.conftest import _make_session, _make_user, _override

BASE_URL = "http://test"
PRIVS_MANAGE = ["users.manage"]


def _make_role(role_id: int, name: str, description: str | None = None) -> Role:
    r = Role()
    r.id = role_id
    r.role_name = name
    r.description = description
    return r


SEEDED_ROLES = [
    _make_role(1, "company_admin", "Full system access"),
    _make_role(2, "receiving_clerk"),
    _make_role(3, "production_supervisor"),
    _make_role(4, "machine_operator"),
]


async def test_list_roles_returns_200():
    user = _make_user()

    def h_roles(r):
        r.scalars.return_value.all.return_value = SEEDED_ROLES

    session = _make_session(user, ["company_admin"], PRIVS_MANAGE, [h_roles])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/roles", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) == 4
        assert [r["role_name"] for r in body["results"]] == [
            "company_admin",
            "receiving_clerk",
            "production_supervisor",
            "machine_operator",
        ]
        assert body["results"][0]["id"] == 1
        assert body["results"][0]["description"] == "Full system access"
        assert body["results"][1]["description"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_list_roles_no_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get("/api/v1/roles")
    assert resp.status_code in (401, 403)


async def test_list_roles_missing_privilege():
    """A clerk without users.manage is refused."""
    user = _make_user()
    session = _make_session(user, ["receiving_clerk"], ["deliveries.create"])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/roles", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_svc_list_roles_empty():
    """An empty roles table yields an empty result list, not an error."""
    from unittest.mock import AsyncMock, MagicMock

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result

    out = await role_service.list_roles(db)
    assert out.results == []
