from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.schemas.contact import ContactListResponse, ContactResponse
from tests.conftest import _make_rbac_session, _override

BASE_URL = "http://test"

_CONTACT_RESPONSE = ContactResponse(
    id=1,
    name="Acme Corp",
    type="client",
    client_code="CLT-001",
    address="123 Main St",
    phone="555-1234",
    notes=None,
    created_at=datetime(2026, 4, 9, tzinfo=timezone.utc),
)

_VALID_BODY = {
    "name": "Acme Corp",
    "type": "client",
    "client_code": "CLT-001",
    "address": "123 Main St",
    "phone": "555-1234",
    "notes": None,
}


# ---------------------------------------------------------------------------
# HTTP Test 1 — GET /contacts → 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_contacts_returns_200():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.view",))
    mock_list = ContactListResponse(total=0, page=1, page_size=20, results=[])

    with patch("app.services.contact_service.list_contacts", new=AsyncMock(return_value=mock_list)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.get(
                    "/api/v1/contacts",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 0
            assert body["page"] == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 2 — GET /contacts without token → 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_contacts_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get("/api/v1/contacts")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# HTTP Test 3 — POST /contacts → 201
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_contact_returns_201():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.manage",))

    with patch("app.services.contact_service.create_contact", new=AsyncMock(return_value=_CONTACT_RESPONSE)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.post(
                    "/api/v1/contacts",
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 201
            body = resp.json()
            assert body["id"] == 1
            assert body["name"] == "Acme Corp"
            assert body["type"] == "client"
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 4 — POST /contacts without token → 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_contact_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.post("/api/v1/contacts", json=_VALID_BODY)
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# HTTP Test 5 — GET /contacts/{id} → 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_contact_returns_200():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.view",))

    with patch("app.services.contact_service.get_contact", new=AsyncMock(return_value=_CONTACT_RESPONSE)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.get(
                    "/api/v1/contacts/1",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["id"] == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 6 — GET /contacts/{id} → 404 when not found
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_contact_returns_404():
    from fastapi import HTTPException

    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.view",))

    with patch(
        "app.services.contact_service.get_contact",
        new=AsyncMock(side_effect=HTTPException(status_code=404, detail="Contact not found")),
    ):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.get(
                    "/api/v1/contacts/9999",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 7 — PATCH /contacts/{id} → 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_update_contact_returns_200():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.manage",))
    updated = _CONTACT_RESPONSE.model_copy(update={"name": "Updated Corp"})

    with patch("app.services.contact_service.update_contact", new=AsyncMock(return_value=updated)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.patch(
                    "/api/v1/contacts/1",
                    json={"name": "Updated Corp"},
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["name"] == "Updated Corp"
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 8 — DELETE /contacts/{id} → 204
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_contact_returns_204():
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("master_data.manage",))

    with patch("app.services.contact_service.delete_contact", new=AsyncMock(return_value=None)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.delete(
                    "/api/v1/contacts/1",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 204
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Service Test 9 — create_contact stores correct fields
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_create_contact_stores_fields():
    from app.services.contact_service import create_contact
    from app.schemas.contact import ContactCreate

    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    data = ContactCreate(
        name="Supplier XYZ",
        type="provider",
        client_code="PRV-001",
        address="456 Oak Ave",
        phone="555-9999",
        notes="Main supplier",
    )

    added_obj = None

    def _add(obj):
        nonlocal added_obj
        added_obj = obj
        obj.id = 42
        obj.created_at = datetime(2026, 4, 9, tzinfo=timezone.utc)

    session.add = MagicMock(side_effect=_add)

    result = await create_contact(db=session, data=data)

    assert result.name == "Supplier XYZ"
    assert result.type == "provider"
    assert result.client_code == "PRV-001"
    assert result.phone == "555-9999"
    assert session.commit.called


# ---------------------------------------------------------------------------
# Service Test 10 — delete_contact removes the record
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_delete_contact_removes_record():
    from app.services.contact_service import delete_contact
    from app.models.contact import Contact

    mock_contact = Contact()
    mock_contact.id = 1
    mock_contact.name = "To Delete"
    mock_contact.type = "client"

    session = AsyncMock()

    get_result = MagicMock()
    get_result.scalar_one_or_none.return_value = mock_contact
    session.execute = AsyncMock(return_value=get_result)
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    await delete_contact(db=session, contact_id=1)

    session.delete.assert_called_once_with(mock_contact)
    session.commit.assert_called_once()
