"""
Tests for T07 — Receiving API (Phase 2: FK refactor).
Expected: 9 passed, 0 failed.
All tests run without a live database connection.
"""
from collections import defaultdict
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.schemas.delivery import (
    DeliveryCreate,
    DeliveryItemCreate,
    DeliveryItemResponse,
    DeliveryListResponse,
    DeliveryResponse,
)
from app.schemas.auth import TokenUser
from tests.conftest import _nested_transaction_mock, _make_rbac_session, _override

BASE_URL = "http://test"

_VALID_ITEM = {
    "product_id": 1,
    "description": "Grade A steel",
    "quantity": 5000,   # 50.00 units ×100
    "pallets": 2,
    "units_per_pallet": 25,
}

_VALID_BODY = {
    "contact_id": 1,
    "carrier_id": 2,
    "delivery_date": "2026-01-15",
    "bol_reference": "BOL-2026-001",
    "items": [_VALID_ITEM],
    "force": False,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_carrier_contact(name="Fast Freight", contact_id=2):
    from app.models.contact import Contact
    c = Contact()
    c.id = contact_id
    c.name = name
    c.type = "carrier"
    return c


def _make_provider_contact(name="Acme Metals", contact_id=1):
    from app.models.contact import Contact
    c = Contact()
    c.id = contact_id
    c.name = name
    c.type = "provider"
    return c


def _make_product(name="Steel Rod", product_id=1, category="raw"):
    from app.models.product import Product
    p = Product()
    p.id = product_id
    p.name = name
    p.category = category
    return p


def _make_flush(
    added,
    delivery_id=1,
    item_base=10,
    inv_base=100,
    contact_id_base=50,
    created_at=None,
    note_id_base=900,
):
    """Return a flush coroutine that assigns DB-generated IDs to added objects."""
    _dt = created_at or datetime(2026, 1, 15, tzinfo=timezone.utc)
    _contact_counter = [contact_id_base]
    _note_counter = [note_id_base]

    async def _flush():
        for contact in added.get("contacts", []):
            if contact.id is None:
                contact.id = _contact_counter[0]
                _contact_counter[0] += 1
        for note in added.get("delivery_notes", []):
            if note.id is None:
                note.id = _note_counter[0]
                note.created_at = _dt
                _note_counter[0] += 1
        for d in added.get("deliveries", []):
            if d.id is None:
                d.id = delivery_id
                d.created_at = _dt
        for idx, item in enumerate(added.get("delivery_items", [])):
            if item.id is None:
                item.id = item_base + idx
        for key in ("inventory_lots", "inventory_items"):
            for idx, inv in enumerate(added.get(key, [])):
                if inv.id is None:
                    inv.id = inv_base + idx

    return _flush


def _make_seq_session(handlers, added, flush_fn=None):
    """Build a mock session with sequential execute handlers."""
    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        n = call_no["n"]
        call_no["n"] += 1
        if n < len(handlers):
            handlers[n](result)
        return result

    session.execute = _execute
    session.add = MagicMock(
        side_effect=lambda obj: added[obj.__class__.__tablename__].append(obj)
    )
    session.flush = flush_fn or AsyncMock()
    session.commit = AsyncMock()
    session.begin_nested = _nested_transaction_mock()
    return session


def _make_mock_delivery_response():
    return DeliveryResponse(
        id=1,
        contact_id=1,
        contact_name="Acme Metals",
        carrier_id=2,
        carrier_name="Fast Freight",
        delivery_date="2026-01-15",
        bol_reference="BOL-2026-001",
        notes=None,
        created_by=1,
        created_by_name="Test User",
        created_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        items=[
            DeliveryItemResponse(
                id=10,
                product_id=1,
                product_name="Steel Rod",
                description="Grade A steel",
                quantity=5000,
                pallets=2,
                units_per_pallet=25,
                leftover=None,
                inventory_lot_id=100,
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
            assert body["items"][0]["inventory_lot_id"] == 100
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

    added = defaultdict(list)
    product = _make_product()
    provider = _make_provider_contact()
    carrier = _make_carrier_contact()

    def _fix_handlers(n, result):
        if n == 0:
            # duplicate-BOL lookup, now against delivery_notes
            result.scalar_one_or_none.return_value = None
        elif n == 1:
            result.scalar_one_or_none.return_value = carrier
        elif n == 2:
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [product]
            result.scalars.return_value = scalars_mock
        elif n == 3:
            # dedupe_document_number: nothing taken
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = []
            result.scalars.return_value = scalars_mock
        elif n == 4:
            # batch contact lookup after commit (provider + carrier)
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [provider, carrier]
            result.scalars.return_value = scalars_mock

    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *a, **kw):
        result = MagicMock()
        n = call_no["n"]
        call_no["n"] += 1
        _fix_handlers(n, result)
        return result

    session.execute = _execute
    session.add = MagicMock(
        side_effect=lambda obj: added[obj.__class__.__tablename__].append(obj)
    )
    session.flush = _make_flush(added, delivery_id=1, item_base=10, inv_base=100)
    session.commit = AsyncMock()
    session.begin_nested = _nested_transaction_mock()

    body = DeliveryCreate(
        contact_id=1,
        carrier_id=2,
        delivery_date="2026-01-15",
        bol_reference="BOL-2026-001",
        items=[
            DeliveryItemCreate(
                product_id=1,
                description="Grade A steel",
                quantity=5000,
                pallets=2,
                units_per_pallet=25,
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

    assert result.id == 1
    assert result.bol_reference == "BOL-2026-001"
    assert result.contact_id == 1
    assert result.carrier_id == 2
    assert result.contact_name == "Acme Metals"
    assert result.carrier_name == "Fast Freight"
    assert len(result.items) == 1
    assert result.items[0].id == 10
    assert result.items[0].product_id == 1
    assert result.items[0].quantity == 5000
    assert result.items[0].inventory_lot_id == 100
    assert result.created_by_name == "Test Clerk"
    assert session.commit.called
    assert len(added["deliveries"]) == 1
    assert len(added["delivery_items"]) == 1
    assert len(added["inventory_lots"]) == 1


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

    body = DeliveryCreate(
        contact_id=1,
        carrier_id=2,
        delivery_date="2026-01-15",
        bol_reference="BOL-2026-001",
        items=[DeliveryItemCreate(product_id=1, quantity=1000)],
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

    existing_delivery = Delivery()
    existing_delivery.id = 99
    existing_delivery.bol_reference = "BOL-DUP"

    added = defaultdict(list)
    product = _make_product()
    provider = _make_provider_contact(name="Acme", contact_id=1)
    carrier = _make_carrier_contact(name="Freight Co", contact_id=2)

    def _fix_handlers(n, result):
        if n == 0:
            result.scalar_one_or_none.return_value = existing_delivery  # exists but force=True
        elif n == 1:
            result.scalar_one_or_none.return_value = carrier
        elif n == 2:
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [product]
            result.scalars.return_value = scalars_mock
        elif n == 3:
            result.scalar_one_or_none.return_value = provider
        elif n == 4:
            result.scalar_one_or_none.return_value = carrier

    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *a, **kw):
        result = MagicMock()
        n = call_no["n"]
        call_no["n"] += 1
        _fix_handlers(n, result)
        return result

    session.execute = _execute
    session.add = MagicMock(
        side_effect=lambda obj: added[obj.__class__.__tablename__].append(obj)
    )
    session.flush = _make_flush(
        added, delivery_id=2, item_base=20, inv_base=200,
        created_at=datetime(2026, 1, 20, tzinfo=timezone.utc),
    )
    session.begin_nested = _nested_transaction_mock()
    session.commit = AsyncMock()

    body = DeliveryCreate(
        contact_id=1,
        carrier_id=2,
        delivery_date="2026-01-20",
        bol_reference="BOL-DUP",
        items=[DeliveryItemCreate(product_id=1, quantity=1000)],
        force=True,
    )
    user = TokenUser(
        user_id=1, full_name="Clerk", roles=[], preferred_language="en",
        effective_privileges=["deliveries.create"],
    )

    result = await create_delivery(body, user, session)

    assert result.id == 2
    assert result.bol_reference == "BOL-DUP"
    assert result.created_by_name == "Clerk"
    assert session.commit.called


# ---------------------------------------------------------------------------
# Service Test 8 — list_deliveries returns paginated DeliveryListResponse
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_list_deliveries_returns_paginated():
    from app.services.delivery_service import list_deliveries
    from app.models.delivery import Delivery, DeliveryItem as DeliveryItemModel

    from app.models.delivery_note import DeliveryNote

    mock_delivery = Delivery()
    mock_delivery.id = 1
    mock_delivery.delivery_note_id = 900
    mock_delivery.carrier_id = None
    mock_delivery.notes = None
    mock_delivery.created_by = 1
    mock_delivery.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)

    # The supplier, reference and date now live on the linked note.
    mock_note = DeliveryNote()
    mock_note.id = 900
    mock_note.type = "inbound"
    mock_note.partner_id = None
    mock_note.document_number = "BOL-2026-001"
    mock_note.document_date = "2026-01-15"
    mock_note.uploaded = True

    mock_item = DeliveryItemModel()
    mock_item.id = 10
    mock_item.delivery_id = 1
    mock_item.product_id = None
    mock_item.description = "Grade A steel"
    mock_item.quantity = 5000
    mock_item.pallets = 2
    mock_item.units_per_pallet = 25
    mock_item.leftover = None
    mock_item.inventory_lot_id = 100

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
            scalars.all.return_value = [mock_delivery]
            result.scalars.return_value = scalars
        elif n == 3:
            scalars = MagicMock()
            scalars.all.return_value = [mock_item]
            result.scalars.return_value = scalars
        elif n == 4:
            scalars = MagicMock()
            scalars.all.return_value = [mock_note]
            result.scalars.return_value = scalars
        elif n == 5:
            from app.models.user import User

            creator = User()
            creator.id = 1
            creator.full_name = "List Test Creator"
            scalars = MagicMock()
            scalars.all.return_value = [creator]
            result.scalars.return_value = scalars
        else:
            scalars = MagicMock()
            scalars.all.return_value = []
            result.scalars.return_value = scalars
        return result

    session.execute = _execute

    result = await list_deliveries(db=session, page=1, page_size=20)

    assert result.total == 1
    assert result.page == 1
    assert len(result.results) == 1
    assert result.results[0].bol_reference == "BOL-2026-001"
    assert result.results[0].contact_name is None
    assert result.results[0].carrier_name is None
    assert len(result.results[0].items) == 1
    assert result.results[0].items[0].inventory_lot_id == 100
    assert result.results[0].created_by_name == "List Test Creator"


# ---------------------------------------------------------------------------
# Service Test 9 — transfer carrier auto-creates Internal provider contact
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_service_transfer_carrier_sets_internal_supplier():
    from app.services.delivery_service import create_delivery

    added = defaultdict(list)
    transfer_carrier = _make_carrier_contact(name="TRANSFERENCIA", contact_id=2)
    product = _make_product(name="BOX-A")

    def _fix_handlers(n, result):
        if n == 0:
            # BOL check → no duplicate
            result.scalar_one_or_none.return_value = None
        elif n == 1:
            # carrier Contact lookup → transfer carrier
            result.scalar_one_or_none.return_value = transfer_carrier
        elif n == 2:
            # Internal contact lookup → not found → will be created
            result.scalar_one_or_none.return_value = None
        elif n == 3:
            # products batch query
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [product]
            result.scalars.return_value = scalars_mock
        elif n == 4:
            # dedupe_document_number: nothing taken
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = []
            result.scalars.return_value = scalars_mock
        elif n == 5:
            # batch contact lookup after commit (internal contact + transfer carrier)
            from app.models.contact import Contact
            internal_contact = Contact()
            internal_contact.id = 50
            internal_contact.name = "Internal"
            internal_contact.type = "provider"
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [internal_contact, transfer_carrier]
            result.scalars.return_value = scalars_mock

    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *a, **kw):
        result = MagicMock()
        n = call_no["n"]
        call_no["n"] += 1
        _fix_handlers(n, result)
        return result

    session.execute = _execute
    session.add = MagicMock(
        side_effect=lambda obj: added[obj.__class__.__tablename__].append(obj)
    )
    session.flush = _make_flush(added, delivery_id=5, item_base=50, inv_base=500, contact_id_base=50)
    session.commit = AsyncMock()
    session.begin_nested = _nested_transaction_mock()

    body = DeliveryCreate(
        contact_id=1,
        carrier_id=2,
        delivery_date="2026-01-15",
        bol_reference="TRANSFER-001",
        items=[DeliveryItemCreate(product_id=1, quantity=1000)],
    )
    user = TokenUser(
        user_id=1, full_name="Clerk", roles=[], preferred_language="en",
        effective_privileges=["deliveries.create"],
    )

    result = await create_delivery(body, user, session)

    assert result.contact_name == "Internal"
    assert result.carrier_name == "TRANSFERENCIA"
    assert result.created_by_name == "Clerk"
    assert result.id == 5
    # Internal contact should have been created and added
    assert len(added["contacts"]) == 1
    assert added["contacts"][0].name == "Internal"
