"""
Tests for Phase 4 — Shipments API, extended by ACR-33 (Transfer/Direct Customer + source).
All tests run without a live database connection.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

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
from tests.conftest import _make_rbac_session, _make_service_session, _override

BASE_URL = "http://test"

_CREATED_AT = datetime(2026, 4, 9, tzinfo=timezone.utc)

_VALID_ITEM = {"lot_id": 1, "quantity": 5000, "unit_price": 250}
_VALID_BODY = {
    "contact_id": 10,
    "carrier_id": 20,
    "bol_number": "AV26-0001",
    "shipment_date": "2026-04-09",
    "type": "direct_customer",
    "source": "SC",
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
        source="SC",
        created_by=1,
        created_at=_CREATED_AT,
        items=[
            ShipmentItemResponse(
                id=100,
                shipment_id=1,
                lot_id=1,
                quantity=5000,
                unit_price=250,
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
        elif isinstance(obj, AuditLog):
            added_audits.append(obj)

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
            # _load_contacts — batch query for client + carrier
            scalars.all.return_value = [client_contact, carrier_contact]
        elif n == 2:
            scalars.all.return_value = [product]
        result.scalars.return_value = scalars
        return result

    async def _flush():
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

    mock_shipment = ShipmentModel()
    mock_shipment.id = 1
    mock_shipment.contact_id = None
    mock_shipment.carrier_id = None
    mock_shipment.bol_number = "AV26-0001"
    mock_shipment.shipment_date = "2026-04-09"
    mock_shipment.notes = None
    mock_shipment.type = "customer_order"
    mock_shipment.created_by = 1
    mock_shipment.created_at = _CREATED_AT

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


# ===========================================================================
# ACR-33 — Transfer / Direct Customer vocabulary, `source`, price snapshot
# ===========================================================================


def _shipping_user():
    return TokenUser(
        user_id=1,
        full_name="Test Clerk",
        roles=["company_admin"],
        preferred_language="en",
        effective_privileges=["shipping.create"],
    )


def _create_session(lot, contacts=(), products=()):
    """Session for `create_shipment` called directly: lots, then contacts, then products."""
    def _rows(rows):
        return lambda result: setattr(
            result.scalars.return_value.all, "return_value", list(rows)
        )

    return _make_service_session(
        [_rows([lot]), _rows(contacts), _rows(products)],
        assign_ids=True,
        created_at=_CREATED_AT,
    )


# ---------------------------------------------------------------------------
# ACR-33 Test 1 — a Direct Customer shipment records `source` (§4.3)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_direct_customer_shipment_records_source():
    from app.services.shipment_service import create_shipment

    lot = _make_lot(lot_id=1, quantity_on_hand=10000)
    session = _create_session(lot)

    body = ShipmentCreate(
        bol_number="AV26-0100",
        shipment_date="2026-07-23",
        type="direct_customer",
        source="SC",
        items=[ShipmentItemCreate(lot_id=1, quantity=5000, unit_price=250)],
    )

    result = await create_shipment(body, _shipping_user(), session)

    assert result.type == "direct_customer"
    assert result.source == "SC"
    assert result.items[0].unit_price == 250


# ---------------------------------------------------------------------------
# ACR-33 Test 2 — `source` on a Transfer note is rejected
# ---------------------------------------------------------------------------
def test_source_on_transfer_shipment_is_rejected():
    with pytest.raises(ValidationError) as exc:
        ShipmentCreate(
            bol_number="AV26-0101",
            shipment_date="2026-07-23",
            type="transfer",
            source="SC",
            items=[ShipmentItemCreate(lot_id=1, quantity=100)],
        )
    assert "direct_customer" in str(exc.value)


@pytest.mark.asyncio
async def test_source_on_transfer_shipment_returns_422_over_http():
    token = create_access_token(user_id=1)
    session = _make_rbac_session_for_shipping()

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/shipments",
                json={**_VALID_BODY, "type": "transfer", "source": "SC"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# ACR-33 Test 3 — a Transfer note without `source` is fine
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_transfer_shipment_without_source_is_accepted():
    from app.services.shipment_service import create_shipment

    lot = _make_lot(lot_id=1, quantity_on_hand=10000)
    session = _create_session(lot)

    body = ShipmentCreate(
        bol_number="AV26-0102",
        shipment_date="2026-07-23",
        type="transfer",
        items=[ShipmentItemCreate(lot_id=1, quantity=1000)],
    )

    result = await create_shipment(body, _shipping_user(), session)

    assert result.type == "transfer"
    assert result.source is None


# ---------------------------------------------------------------------------
# ACR-33 Test 4 — the retired vocabulary no longer validates
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("retired_type", ["customer_order", "transfer_out", "", "DIRECT_CUSTOMER"])
def test_retired_shipment_types_are_rejected(retired_type):
    with pytest.raises(ValidationError):
        ShipmentCreate(
            bol_number="AV26-0103",
            shipment_date="2026-07-23",
            type=retired_type,
            items=[ShipmentItemCreate(lot_id=1, quantity=100)],
        )


# ---------------------------------------------------------------------------
# ACR-33 Test 5 — field validation on the create payload
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides",
    [
        {"bol_number": ""},                 # empty
        {"bol_number": "   "},              # whitespace only
        {"bol_number": "X" * 101},          # over max_length
        {"shipment_date": "  "},            # whitespace only
        {"source": "   "},                  # whitespace only
        {"source": "S" * 51},               # over max_length
        {"items": []},                      # no lines
    ],
)
def test_invalid_shipment_payloads_are_rejected(overrides):
    payload = {
        "bol_number": "AV26-0104",
        "shipment_date": "2026-07-23",
        "type": "direct_customer",
        "items": [{"lot_id": 1, "quantity": 100}],
    }
    payload.update(overrides)
    with pytest.raises(ValidationError):
        ShipmentCreate(**payload)


@pytest.mark.parametrize(
    "item_overrides",
    [
        {"quantity": 0},
        {"quantity": -100},
        {"unit_price": -1},
        {"lot_id": 0},
        {"lot_id": -3},
    ],
)
def test_invalid_shipment_line_values_are_rejected(item_overrides):
    item = {"lot_id": 1, "quantity": 100}
    item.update(item_overrides)
    with pytest.raises(ValidationError):
        ShipmentCreate(
            bol_number="AV26-0105",
            shipment_date="2026-07-23",
            items=[item],
        )


# ---------------------------------------------------------------------------
# ACR-33 Test 6 — BOTH types write the Issue movement against the ledger
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("shipment_type", ["transfer", "direct_customer"])
@pytest.mark.asyncio
async def test_both_shipment_types_write_issue_movement(shipment_type):
    from app.models.inventory import InventoryTransaction
    from app.services.shipment_service import create_shipment

    lot = _make_lot(lot_id=1, quantity_on_hand=10000)
    session = _create_session(lot)

    body = ShipmentCreate(
        bol_number=f"AV26-{shipment_type}",
        shipment_date="2026-07-23",
        type=shipment_type,
        items=[ShipmentItemCreate(lot_id=1, quantity=4000)],
    )

    await create_shipment(body, _shipping_user(), session)

    txns = [o for o in session.added if isinstance(o, InventoryTransaction)]
    assert len(txns) == 1
    assert txns[0].transaction_type == "ship"
    assert txns[0].quantity == -4000          # negative: an Issue, per domain model §4.1
    assert txns[0].reference_type == "shipment"
    assert lot.quantity_on_hand == 6000


# ---------------------------------------------------------------------------
# ACR-33 Test 7 — an unpriced line is allowed (price is optional at ship time)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_shipment_line_without_unit_price_is_allowed():
    from app.services.shipment_service import create_shipment

    lot = _make_lot(lot_id=1, quantity_on_hand=10000)
    session = _create_session(lot)

    body = ShipmentCreate(
        bol_number="AV26-0106",
        shipment_date="2026-07-23",
        items=[ShipmentItemCreate(lot_id=1, quantity=1000)],
    )

    result = await create_shipment(body, _shipping_user(), session)

    assert result.items[0].unit_price is None


# ---------------------------------------------------------------------------
# ACR-33 Test 8 — `type` defaults to direct_customer
# ---------------------------------------------------------------------------
def test_shipment_type_defaults_to_direct_customer():
    body = ShipmentCreate(
        bol_number="AV26-0107",
        shipment_date="2026-07-23",
        items=[ShipmentItemCreate(lot_id=1, quantity=100)],
    )
    assert body.type == "direct_customer"
    assert body.source is None


# ---------------------------------------------------------------------------
# ACR-33 Test 9 — surrounding whitespace is trimmed, not preserved
# ---------------------------------------------------------------------------
def test_shipment_string_fields_are_trimmed():
    body = ShipmentCreate(
        bol_number="  AV26-0108  ",
        shipment_date=" 2026-07-23 ",
        source="  SC  ",
        items=[ShipmentItemCreate(lot_id=1, quantity=100)],
    )
    assert body.bol_number == "AV26-0108"
    assert body.shipment_date == "2026-07-23"
    assert body.source == "SC"
