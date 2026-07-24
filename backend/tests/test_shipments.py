"""
Tests for Phase 4 — Shipments API.
Expected: 9 passed, 0 failed.
All tests run without a live database connection.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.schemas.auth import TokenUser
from app.schemas.shipment import (
    ShipmentCreate,
    ShipmentItemCreate,
    ShipmentItemResponse,
    ShipmentListResponse,
    ShipmentResponse,
)
from tests.conftest import _nested_transaction_mock, _make_rbac_session, _override

BASE_URL = "http://test"

_CREATED_AT = datetime(2026, 4, 9, tzinfo=timezone.utc)

_VALID_ITEM = {"lot_id": 1, "quantity": 5000}
_VALID_BODY = {
    "contact_id": 10,
    "carrier_id": 20,
    "bol_number": "AV26-0001",
    "shipment_date": "2026-04-09",
    "type": "direct_customer",
    "items": [_VALID_ITEM],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lot(lot_id=1, quantity_on_hand=10000, status="in_storage", product_id=5):
    from app.models.inventory import InventoryLot

    lot = InventoryLot()
    lot.id = lot_id
    lot.product_id = product_id
    lot.lot_number = f"LOT-{lot_id:04d}"
    lot.storage_location = "A-01"
    lot.status = status
    lot.quantity_on_hand = quantity_on_hand
    lot.pallet_number = None
    return lot


def _make_client_contact(contact_id=10, name="Acme Corp"):
    from app.models.contact import Contact

    c = Contact()
    c.id = contact_id
    c.name = name
    c.type = "client"
    return c


def _make_carrier_contact(contact_id=20, name="Fast Freight"):
    from app.models.contact import Contact

    c = Contact()
    c.id = contact_id
    c.name = name
    c.type = "carrier"
    return c


def _make_product(product_id=5, name="Steel Rod"):
    from app.models.product import Product

    p = Product()
    p.id = product_id
    p.name = name
    p.category = "finished"
    return p


def _make_mock_shipment_response():
    return ShipmentResponse(
        id=1,
        contact_id=10,
        contact_name="Acme Corp",
        carrier_id=20,
        carrier_name="Fast Freight",
        bol_number="AV26-0001",
        shipment_date="2026-04-09",
        notes=None,
        type="direct_customer",
        created_by=1,
        created_at=_CREATED_AT,
        items=[
            ShipmentItemResponse(
                id=100,
                shipment_id=1,
                lot_id=1,
                quantity=5000,
                product_name="Steel Rod",
                lot_number="LOT-0001",
            )
        ],
    )


def _make_rbac_session_for_shipping():
    return _make_rbac_session(privileges=("shipping.view", "shipping.create"))


# ---------------------------------------------------------------------------
# HTTP Test 1 — POST /shipments → 201
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_shipment_returns_201():
    token = create_access_token(user_id=1)
    session = _make_rbac_session_for_shipping()
    mock_resp = _make_mock_shipment_response()

    with patch(
        "app.services.shipment_service.create_shipment",
        new=AsyncMock(return_value=mock_resp),
    ):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.post(
                    "/api/v1/shipments",
                    json=_VALID_BODY,
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 201
            body = resp.json()
            assert body["id"] == 1
            assert body["bol_number"] == "AV26-0001"
            assert len(body["items"]) == 1
            assert body["items"][0]["lot_id"] == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 2 — POST /shipments without auth → 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_shipment_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.post("/api/v1/shipments", json=_VALID_BODY)
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# HTTP Test 3 — GET /shipments → 200 paginated
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_shipments_returns_200():
    token = create_access_token(user_id=1)
    session = _make_rbac_session_for_shipping()
    mock_list = ShipmentListResponse(
        total=1,
        page=1,
        page_size=20,
        results=[_make_mock_shipment_response()],
    )

    with patch(
        "app.services.shipment_service.list_shipments",
        new=AsyncMock(return_value=mock_list),
    ):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.get(
                    "/api/v1/shipments",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 1
            assert len(body["results"]) == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# HTTP Test 4 — GET /shipments without auth → 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_shipments_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get("/api/v1/shipments")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Service Test 5 — create_shipment happy path: deducts stock + writes txn
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_create_shipment_deducts_stock():
    from app.services.shipment_service import create_shipment

    lot = _make_lot(lot_id=1, quantity_on_hand=10000)  # 100.00 units
    client_contact = _make_client_contact()
    carrier_contact = _make_carrier_contact()
    product = _make_product()

    added_shipments = []
    added_items = []
    added_txns = []
    added_audits = []

    added_notes = []

    def _side_effect(obj):
        from app.models.shipment import Shipment, ShipmentItem
        from app.models.inventory import InventoryTransaction
        from app.models.audit import AuditLog
        from app.models.delivery_note import DeliveryNote

        if isinstance(obj, Shipment):
            added_shipments.append(obj)
        elif isinstance(obj, ShipmentItem):
            added_items.append(obj)
        elif isinstance(obj, InventoryTransaction):
            added_txns.append(obj)
        elif isinstance(obj, AuditLog):
            added_audits.append(obj)
        elif isinstance(obj, DeliveryNote):
            added_notes.append(obj)

    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *a, **kw):
        result = MagicMock()
        n = call_no["n"]
        call_no["n"] += 1
        scalars = MagicMock()
        if n == 0:
            scalars.all.return_value = [lot]
        elif n == 1:
            # dedupe_document_number — nothing taken
            scalars.all.return_value = []
        elif n == 2:
            # _load_contacts — batch query for client + carrier
            scalars.all.return_value = [client_contact, carrier_contact]
        elif n == 3:
            scalars.all.return_value = [product]
        result.scalars.return_value = scalars
        return result

    async def _flush():
        for note in added_notes:
            if note.id is None:
                note.id = 900
                note.created_at = _CREATED_AT
        for s in added_shipments:
            if s.id is None:
                s.id = 1
                s.created_at = _CREATED_AT
        for idx, it in enumerate(added_items):
            if it.id is None:
                it.id = 100 + idx

    session.execute = _execute
    session.add = MagicMock(side_effect=_side_effect)
    session.flush = _flush
    session.commit = AsyncMock()
    session.begin_nested = _nested_transaction_mock()

    body = ShipmentCreate(
        contact_id=10,
        carrier_id=20,
        bol_number="AV26-0001",
        shipment_date="2026-04-09",
        items=[ShipmentItemCreate(lot_id=1, quantity=5000)],
    )
    user = TokenUser(
        user_id=1,
        full_name="Test Clerk",
        roles=["shipping_clerk"],
        preferred_language="en",
        effective_privileges=["shipping.create"],
    )

    result = await create_shipment(body, user, session)

    # Stock deducted: 10000 - 5000 = 5000
    assert lot.quantity_on_hand == 5000
    # Status not changed (stock > 0)
    assert lot.status == "in_storage"
    # Transaction written
    assert len(added_txns) == 1
    txn = added_txns[0]
    assert txn.transaction_type == "ship"
    assert txn.quantity == -5000
    assert txn.lot_id == 1
    # Response correct
    assert result.id == 1
    assert result.bol_number == "AV26-0001"
    assert result.contact_name == "Acme Corp"
    assert result.carrier_name == "Fast Freight"
    assert len(result.items) == 1
    assert result.items[0].quantity == 5000
    assert session.commit.called


# ---------------------------------------------------------------------------
# Service Test 6 — insufficient stock raises 422
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_insufficient_stock_raises_422():
    from fastapi import HTTPException
    from app.services.shipment_service import create_shipment

    lot = _make_lot(lot_id=1, quantity_on_hand=100)  # only 1.00 unit

    session = AsyncMock()

    async def _execute(query, *a, **kw):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = [lot]
        result.scalars.return_value = scalars
        return result

    session.execute = _execute

    body = ShipmentCreate(
        contact_id=10,
        carrier_id=None,
        bol_number="AV26-0002",
        shipment_date="2026-04-09",
        items=[ShipmentItemCreate(lot_id=1, quantity=5000)],  # 50.00 > 1.00
    )
    user = TokenUser(
        user_id=1,
        full_name="Clerk",
        roles=[],
        preferred_language="en",
        effective_privileges=["shipping.create"],
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_shipment(body, user, session)

    assert exc_info.value.status_code == 422
    assert "Insufficient stock" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Service Test 7 — lot status flips to 'shipped' when stock reaches zero
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_lot_status_set_to_shipped_when_zero():
    from app.services.shipment_service import create_shipment

    lot = _make_lot(lot_id=1, quantity_on_hand=5000)  # exactly 50.00 units
    client_contact = _make_client_contact()
    product = _make_product()

    added_items = []
    added_txns = []
    added_shipments = []

    def _side_effect(obj):
        from app.models.shipment import Shipment, ShipmentItem
        from app.models.inventory import InventoryTransaction
        from app.models.audit import AuditLog

        if isinstance(obj, Shipment):
            added_shipments.append(obj)
        elif isinstance(obj, ShipmentItem):
            added_items.append(obj)
        elif isinstance(obj, InventoryTransaction):
            added_txns.append(obj)

    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *a, **kw):
        result = MagicMock()
        n = call_no["n"]
        call_no["n"] += 1
        if n == 0:
            scalars = MagicMock()
            scalars.all.return_value = [lot]
            result.scalars.return_value = scalars
        elif n == 1:
            result.scalar_one_or_none.return_value = client_contact
        elif n == 2:
            result.scalar_one_or_none.return_value = None  # no carrier
        elif n == 3:
            scalars = MagicMock()
            scalars.all.return_value = [product]
            result.scalars.return_value = scalars
        return result

    async def _flush():
        for s in added_shipments:
            if s.id is None:
                s.id = 2
                s.created_at = _CREATED_AT
        for idx, it in enumerate(added_items):
            if it.id is None:
                it.id = 200 + idx

    session.execute = _execute
    session.add = MagicMock(side_effect=_side_effect)
    session.flush = _flush
    session.commit = AsyncMock()
    session.begin_nested = _nested_transaction_mock()

    body = ShipmentCreate(
        contact_id=10,
        carrier_id=None,
        bol_number="AV26-0003",
        shipment_date="2026-04-09",
        items=[ShipmentItemCreate(lot_id=1, quantity=5000)],  # exact remaining stock
    )
    user = TokenUser(
        user_id=1,
        full_name="Clerk",
        roles=[],
        preferred_language="en",
        effective_privileges=["shipping.create"],
    )

    await create_shipment(body, user, session)

    assert lot.quantity_on_hand == 0
    assert lot.status == "shipped"


# ---------------------------------------------------------------------------
# Service Test 8 — lot not found raises 404
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_lot_not_found_raises_404():
    from fastapi import HTTPException
    from app.services.shipment_service import create_shipment

    session = AsyncMock()

    async def _execute(query, *a, **kw):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []  # no lots found
        result.scalars.return_value = scalars
        return result

    session.execute = _execute

    body = ShipmentCreate(
        contact_id=None,
        carrier_id=None,
        bol_number="AV26-0004",
        shipment_date="2026-04-09",
        items=[ShipmentItemCreate(lot_id=999, quantity=1000)],
    )
    user = TokenUser(
        user_id=1,
        full_name="Clerk",
        roles=[],
        preferred_language="en",
        effective_privileges=["shipping.create"],
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_shipment(body, user, session)

    assert exc_info.value.status_code == 404
    assert "999" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Service Test 9 — list_shipments returns paginated ShipmentListResponse
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_list_shipments_returns_paginated():
    from app.services.shipment_service import list_shipments
    from app.models.shipment import Shipment as ShipmentModel

    from app.models.delivery_note import DeliveryNote

    mock_shipment = ShipmentModel()
    mock_shipment.id = 1
    mock_shipment.delivery_note_id = 900
    mock_shipment.carrier_id = None
    mock_shipment.notes = None
    mock_shipment.created_by = 1
    mock_shipment.created_at = _CREATED_AT

    # The client, BoL number, date and flavour now live on the linked note.
    mock_note = DeliveryNote()
    mock_note.id = 900
    mock_note.type = "direct_customer"
    mock_note.partner_id = None
    mock_note.source = None
    mock_note.document_number = "AV26-0001"
    mock_note.document_date = "2026-04-09"
    mock_note.uploaded = False

    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        call_no["n"] += 1
        n = call_no["n"]
        if n == 1:
            result.scalar.return_value = 1
        elif n == 2:
            scalars = MagicMock()
            scalars.all.return_value = [mock_shipment]
            result.scalars.return_value = scalars
        elif n == 4:
            # _load_notes
            scalars = MagicMock()
            scalars.all.return_value = [mock_note]
            result.scalars.return_value = scalars
        else:
            scalars = MagicMock()
            scalars.all.return_value = []
            result.scalars.return_value = scalars
        return result

    session.execute = _execute

    result = await list_shipments(db=session, page=1, page_size=20)

    assert result.total == 1
    assert result.page == 1
    assert len(result.results) == 1
    assert result.results[0].bol_number == "AV26-0001"
    assert result.results[0].contact_name is None
    assert result.results[0].items == []
