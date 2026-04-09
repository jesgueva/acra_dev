"""
Tests for T07 — Receiving API.
Expected: 8 passed, 0 failed (includes force=True scenario).
All tests run without a live database connection.
"""
from collections import defaultdict
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.user import User
from app.schemas.delivery import (
    DeliveryCreate,
    DeliveryItemCreate,
    DeliveryItemResponse,
    DeliveryListResponse,
    DeliveryResponse,
)
from app.schemas.auth import TokenUser

BASE_URL = "http://test"

_VALID_ITEM = {
    "material_type": "Steel Rod",
    "quantity": 50.0,
    "lot_batch_number": "LOT-001",
    "storage_location": "A-1",
}

_VALID_BODY = {
    "supplier": "Acme Metals",
    "carrier": "Fast Freight",
    "delivery_date": "2026-01-15",
    "bol_reference": "BOL-2026-001",
    "items": [_VALID_ITEM],
    "force": False,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user() -> User:
    u = User()
    u.id = 1
    u.username = "clerk"
    u.full_name = "Test Clerk"
    u.preferred_language = "en"
    u.status = "active"
    u.password_hash = hash_password("pass")
    return u


def _make_rbac_session(privileges=("deliveries.create", "deliveries.view")):
    """Mock session that satisfies the 3 RBAC execute() calls."""
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


def _override(session):
    async def _dep():
        yield session
    return _dep


def _make_mock_delivery_response():
    return DeliveryResponse(
        id=1,
        supplier="Acme Metals",
        carrier="Fast Freight",
        delivery_date=date(2026, 1, 15),
        bol_reference="BOL-2026-001",
        created_by=1,
        created_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        items=[
            DeliveryItemResponse(
                id=10,
                material_type="Steel Rod",
                quantity=50.0,
                lot_batch_number="LOT-001",
                storage_location="A-1",
                inventory_item_id=100,
            )
        ],
    )


# ---------------------------------------------------------------------------
# HTTP Test 1 — POST /deliveries succeeds with valid token → 201
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_delivery_returns_201():
    token = create_access_token(user_id=1)
    session = _make_rbac_session()
    mock_resp = _make_mock_delivery_response()

    with patch(
        "app.services.delivery_service.create_delivery",
        new=AsyncMock(return_value=mock_resp),
    ):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.post(
                    "/api/v1/deliveries",
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 201
            body = resp.json()
            assert body["id"] == 1
            assert body["bol_reference"] == "BOL-2026-001"
            assert len(body["items"]) == 1
            assert body["items"][0]["inventory_item_id"] == 100
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 2 — POST /deliveries without token → 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_delivery_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.post("/api/v1/deliveries", json=_VALID_BODY)
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# HTTP Test 3 — GET /deliveries with valid token → 200 paginated response
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_deliveries_returns_200():
    token = create_access_token(user_id=1)
    session = _make_rbac_session()
    mock_list = DeliveryListResponse(
        total=1,
        page=1,
        page_size=20,
        results=[_make_mock_delivery_response()],
    )

    with patch(
        "app.services.delivery_service.list_deliveries",
        new=AsyncMock(return_value=mock_list),
    ):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.get(
                    "/api/v1/deliveries",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 1
            assert body["page"] == 1
            assert len(body["results"]) == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 4 — GET /deliveries without token → 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_deliveries_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get("/api/v1/deliveries")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Service Test 5 — create_delivery is atomic: commits and links inventory IDs
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_create_delivery_atomic():
    from app.services.delivery_service import create_delivery

    # Build mock session
    session = AsyncMock()

    bol_result = MagicMock()
    bol_result.scalar_one_or_none.return_value = None  # no duplicate
    session.execute = AsyncMock(return_value=bol_result)

    added = defaultdict(list)

    def _add(obj):
        added[obj.__class__.__tablename__].append(obj)

    session.add = MagicMock(side_effect=_add)

    flush_count = [0]

    async def _flush():
        flush_count[0] += 1
        n = flush_count[0]
        if n == 1:  # after Delivery
            for d in added.get("deliveries", []):
                if d.id is None:
                    d.id = 1
                    d.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
        elif n == 2:  # after DeliveryItems
            for idx, item in enumerate(added.get("delivery_items", [])):
                if item.id is None:
                    item.id = 10 + idx
        elif n == 3:  # after InventoryItems
            for idx, inv in enumerate(added.get("inventory_items", [])):
                if inv.id is None:
                    inv.id = 100 + idx

    session.flush = _flush
    session.commit = AsyncMock()

    body = DeliveryCreate(
        supplier="Acme Metals",
        carrier="Fast Freight",
        delivery_date=date(2026, 1, 15),
        bol_reference="BOL-2026-001",
        items=[
            DeliveryItemCreate(
                material_type="Steel Rod",
                quantity=50.0,
                lot_batch_number="LOT-001",
                storage_location="A-1",
            )
        ],
    )
    user = TokenUser(
        user_id=1,
        full_name="Test Clerk",
        roles=["receiving_clerk"],
        preferred_language="en",
        effective_privileges=["deliveries.create"],
    )

    result = await create_delivery(body, user, session)

    # Delivery was created with correct ID
    assert result.id == 1
    assert result.bol_reference == "BOL-2026-001"
    # Item was created and linked to inventory
    assert len(result.items) == 1
    assert result.items[0].id == 10
    assert result.items[0].inventory_item_id == 100
    # Session was committed
    assert session.commit.called
    # Correct tables populated
    assert len(added["deliveries"]) == 1
    assert len(added["delivery_items"]) == 1
    assert len(added["inventory_items"]) == 1


# ---------------------------------------------------------------------------
# Service Test 6 — duplicate BOL raises 409 when force=False
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_duplicate_bol_raises_409():
    from fastapi import HTTPException
    from app.services.delivery_service import create_delivery
    from app.models.delivery import Delivery

    existing = Delivery()
    existing.id = 99
    existing.bol_reference = "BOL-2026-001"

    session = AsyncMock()
    bol_result = MagicMock()
    bol_result.scalar_one_or_none.return_value = existing
    session.execute = AsyncMock(return_value=bol_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    body = DeliveryCreate(
        supplier="Acme",
        carrier="Freight Co",
        delivery_date=date(2026, 1, 15),
        bol_reference="BOL-2026-001",
        items=[DeliveryItemCreate(material_type="Steel", quantity=1.0, lot_batch_number="L1", storage_location="A1")],
        force=False,
    )
    user = TokenUser(
        user_id=1, full_name="Clerk", roles=[], preferred_language="en",
        effective_privileges=["deliveries.create"],
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_delivery(body, user, session)

    assert exc_info.value.status_code == 409
    assert "BOL-2026-001" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Service Test 7 — force=True overrides duplicate BOL and creates delivery
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_force_true_overrides_duplicate():
    from app.services.delivery_service import create_delivery
    from app.models.delivery import Delivery

    existing = Delivery()
    existing.id = 99
    existing.bol_reference = "BOL-DUP"

    session = AsyncMock()
    bol_result = MagicMock()
    bol_result.scalar_one_or_none.return_value = existing  # duplicate exists
    session.execute = AsyncMock(return_value=bol_result)

    added = defaultdict(list)

    def _add(obj):
        added[obj.__class__.__tablename__].append(obj)

    session.add = MagicMock(side_effect=_add)

    async def _flush():
        for d in added.get("deliveries", []):
            if d.id is None:
                d.id = 2
                d.created_at = datetime(2026, 1, 20, tzinfo=timezone.utc)
        for idx, item in enumerate(added.get("delivery_items", [])):
            if item.id is None:
                item.id = 20 + idx
        for idx, inv in enumerate(added.get("inventory_items", [])):
            if inv.id is None:
                inv.id = 200 + idx

    session.flush = _flush
    session.commit = AsyncMock()

    body = DeliveryCreate(
        supplier="Acme",
        carrier="Freight Co",
        delivery_date=date(2026, 1, 20),
        bol_reference="BOL-DUP",
        items=[DeliveryItemCreate(material_type="Steel", quantity=10.0, lot_batch_number="L2", storage_location="B1")],
        force=True,  # override duplicate
    )
    user = TokenUser(
        user_id=1, full_name="Clerk", roles=[], preferred_language="en",
        effective_privileges=["deliveries.create"],
    )

    result = await create_delivery(body, user, session)

    assert result.id == 2
    assert result.bol_reference == "BOL-DUP"
    assert session.commit.called


# ---------------------------------------------------------------------------
# Service Test 8 — list_deliveries returns paginated DeliveryListResponse
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_list_deliveries_returns_paginated():
    from app.services.delivery_service import list_deliveries
    from app.models.delivery import Delivery, DeliveryItem as DeliveryItemModel

    mock_delivery = Delivery()
    mock_delivery.id = 1
    mock_delivery.supplier = "Acme Metals"
    mock_delivery.carrier = "Fast Freight"
    mock_delivery.delivery_date = date(2026, 1, 15)
    mock_delivery.bol_reference = "BOL-2026-001"
    mock_delivery.created_by = 1
    mock_delivery.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)

    mock_item = DeliveryItemModel()
    mock_item.id = 10
    mock_item.delivery_id = 1
    mock_item.material_type = "Steel Rod"
    mock_item.quantity = 50.0
    mock_item.lot_batch_number = "LOT-001"
    mock_item.storage_location = "A-1"
    mock_item.inventory_item_id = 100

    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        call_no["n"] += 1
        n = call_no["n"]
        if n == 1:  # count
            result.scalar.return_value = 1
        elif n == 2:  # list deliveries
            scalars = MagicMock()
            scalars.all.return_value = [mock_delivery]
            result.scalars.return_value = scalars
        else:  # list items
            scalars = MagicMock()
            scalars.all.return_value = [mock_item]
            result.scalars.return_value = scalars
        return result

    session.execute = _execute

    result = await list_deliveries(db=session, page=1, page_size=20)

    assert result.total == 1
    assert result.page == 1
    assert len(result.results) == 1
    assert result.results[0].bol_reference == "BOL-2026-001"
    assert len(result.results[0].items) == 1
    assert result.results[0].items[0].inventory_item_id == 100
