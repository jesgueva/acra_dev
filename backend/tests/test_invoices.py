"""
Tests for ACR-33 — Invoice generation against a shipment.
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
from app.schemas.invoice import InvoiceLineResponse, InvoiceResponse
from app.services import invoice_service
from tests.conftest import _make_rbac_session, _make_service_session, _override

BASE_URL = "http://test"

_CREATED_AT = datetime(2026, 7, 23, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_shipment(shipment_id=1, shipment_date="2026-07-23", contact_id=10):
    from app.models.shipment import Shipment

    s = Shipment()
    s.id = shipment_id
    s.contact_id = contact_id
    s.carrier_id = None
    s.bol_number = "AV26-0001"
    s.shipment_date = shipment_date
    s.notes = None
    s.type = "direct_customer"
    s.source = "SC"
    s.created_by = 1
    s.created_at = _CREATED_AT
    return s


def _make_shipment_item(item_id=100, shipment_id=1, lot_id=1, quantity=5000, unit_price=250):
    from app.models.shipment import ShipmentItem

    si = ShipmentItem()
    si.id = item_id
    si.shipment_id = shipment_id
    si.lot_id = lot_id
    si.quantity = quantity
    si.unit_price = unit_price
    return si


def _make_invoice(invoice_id=1, shipment_id=1, number="INV-2026-00001", subtotal=12500):
    from app.models.invoice import Invoice

    inv = Invoice()
    inv.id = invoice_id
    inv.shipment_id = shipment_id
    inv.invoice_number = number
    inv.invoice_date = "2026-07-23"
    inv.currency = "USD"
    inv.subtotal_amount = subtotal
    inv.tax_amount = 0
    inv.total_amount = subtotal
    inv.status = "issued"
    inv.created_by = 1
    inv.created_at = _CREATED_AT
    return inv


def _make_invoice_line(line_id=1, invoice_id=1, shipment_item_id=100):
    from app.models.invoice import InvoiceLine

    line = InvoiceLine()
    line.id = line_id
    line.invoice_id = invoice_id
    line.shipment_item_id = shipment_item_id
    line.description = "Steel Rod (lot LOT-0001)"
    line.quantity = 5000
    line.unit_price = 250
    line.line_total = 12500
    return line


def _make_mock_invoice_response():
    return InvoiceResponse(
        id=1,
        shipment_id=1,
        invoice_number="INV-2026-00001",
        invoice_date="2026-07-23",
        currency="USD",
        subtotal_amount=12500,
        tax_amount=0,
        total_amount=12500,
        status="issued",
        created_by=1,
        created_at=_CREATED_AT,
        bol_number="AV26-0001",
        contact_name="Acme Corp",
        lines=[
            InvoiceLineResponse(
                id=1,
                invoice_id=1,
                shipment_item_id=100,
                description="Steel Rod (lot LOT-0001)",
                quantity=5000,
                unit_price=250,
                line_total=12500,
            )
        ],
    )


def _rbac_session(privileges=("shipping.view", "shipping.create")):
    return _make_rbac_session(privileges=privileges)


def _flushing_session(handlers):
    """`generate_invoice` reads `invoice.id` right after its first flush, so ids must be assigned."""
    return _make_service_session(handlers, assign_ids=True, created_at=_CREATED_AT)


def _token_user():
    return TokenUser(
        user_id=1,
        full_name="Test User",
        roles=["company_admin"],
        preferred_language="en",
        effective_privileges=["shipping.view", "shipping.create"],
    )


# ---------------------------------------------------------------------------
# HTTP 1 — POST /shipments/{id}/invoice → 201
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_invoice_returns_201():
    token = create_access_token(user_id=1)
    session = _rbac_session()

    with patch(
        "app.services.invoice_service.generate_invoice",
        new=AsyncMock(return_value=_make_mock_invoice_response()),
    ):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.post(
                    "/api/v1/shipments/1/invoice",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 201
            body = resp.json()
            assert body["invoice_number"] == "INV-2026-00001"
            assert body["total_amount"] == 12500
            assert len(body["lines"]) == 1
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# HTTP 2 — RBAC: POST without shipping.create → 403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_invoice_without_privilege_returns_403():
    token = create_access_token(user_id=1)
    session = _rbac_session(privileges=("shipping.view",))

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/shipments/1/invoice",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# HTTP 3 — no auth header → 401/403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_invoice_without_auth_is_rejected():
    session = _rbac_session()
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post("/api/v1/shipments/1/invoice")
        assert resp.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# HTTP 4 — GET /shipments/{id}/invoice → 200
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_invoice_returns_200():
    token = create_access_token(user_id=1)
    session = _rbac_session()

    with patch(
        "app.services.invoice_service.get_invoice_for_shipment",
        new=AsyncMock(return_value=_make_mock_invoice_response()),
    ):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
                resp = await client.get(
                    "/api/v1/shipments/1/invoice",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["lines"][0]["shipment_item_id"] == 100
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# HTTP 5 — RBAC: GET without shipping.view → 403
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_invoice_without_privilege_returns_403():
    token = create_access_token(user_id=1)
    session = _rbac_session(privileges=("deliveries.view",))

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/shipments/1/invoice",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Service 1 — happy path: totals, number, audit
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_invoice_service_computes_totals():
    shipment = _make_shipment()
    items = [
        _make_shipment_item(item_id=100, quantity=5000, unit_price=250),   # 125.00
        _make_shipment_item(item_id=101, lot_id=2, quantity=200, unit_price=1000),  # 20.00
    ]

    def h_shipment(result):
        result.scalar_one_or_none.return_value = shipment

    def h_existing(result):
        result.scalar_one_or_none.return_value = None

    def h_items(result):
        result.scalars.return_value.all.return_value = items

    def h_lots(result):
        result.scalars.return_value.all.return_value = []

    def h_contact(result):
        result.scalar_one_or_none.return_value = None

    session = _flushing_session([h_shipment, h_existing, h_items, h_lots, h_contact])

    resp = await invoice_service.generate_invoice(
        1, _token_user(), session
    )

    # 5000×250/100 = 12500 ; 200×1000/100 = 2000
    assert resp.subtotal_amount == 14500
    assert resp.tax_amount == 0
    assert resp.total_amount == 14500
    assert resp.invoice_number == "INV-2026-00001"
    assert len(resp.lines) == 2


# ---------------------------------------------------------------------------
# Service 2 — an unpriced line contributes 0, still appears
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_invoice_treats_null_unit_price_as_zero():
    items = [
        _make_shipment_item(item_id=100, quantity=5000, unit_price=250),
        _make_shipment_item(item_id=101, lot_id=2, quantity=300, unit_price=None),
    ]

    handlers = [
        lambda r: setattr(r.scalar_one_or_none, "return_value", _make_shipment()),
        lambda r: setattr(r.scalar_one_or_none, "return_value", None),
        lambda r: setattr(r.scalars.return_value.all, "return_value", items),
        lambda r: setattr(r.scalars.return_value.all, "return_value", []),
        lambda r: setattr(r.scalar_one_or_none, "return_value", None),
    ]
    session = _flushing_session(handlers)

    resp = await invoice_service.generate_invoice(
        1, _token_user(), session
    )

    assert resp.subtotal_amount == 12500
    assert len(resp.lines) == 2
    assert resp.lines[1].unit_price == 0
    assert resp.lines[1].line_total == 0


# ---------------------------------------------------------------------------
# Service 3 — unknown shipment → 404
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_invoice_unknown_shipment_raises_404():
    from fastapi import HTTPException

    session = _make_service_session([lambda r: setattr(r.scalar_one_or_none, "return_value", None)])

    with pytest.raises(HTTPException) as exc:
        await invoice_service.generate_invoice(
            999, _token_user(), session
        )
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Service 4 — invoice already exists → 409 (invoices are immutable)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_invoice_twice_raises_409():
    from fastapi import HTTPException

    handlers = [
        lambda r: setattr(r.scalar_one_or_none, "return_value", _make_shipment()),
        lambda r: setattr(r.scalar_one_or_none, "return_value", _make_invoice()),
    ]
    session = _make_service_session(handlers)

    with pytest.raises(HTTPException) as exc:
        await invoice_service.generate_invoice(
            1, _token_user(), session
        )
    assert exc.value.status_code == 409
    assert "INV-2026-00001" in exc.value.detail


# ---------------------------------------------------------------------------
# Service 5 — shipment with no items → 422
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_invoice_with_no_items_raises_422():
    from fastapi import HTTPException

    handlers = [
        lambda r: setattr(r.scalar_one_or_none, "return_value", _make_shipment()),
        lambda r: setattr(r.scalar_one_or_none, "return_value", None),
        lambda r: setattr(r.scalars.return_value.all, "return_value", []),
    ]
    session = _make_service_session(handlers)

    with pytest.raises(HTTPException) as exc:
        await invoice_service.generate_invoice(
            1, _token_user(), session
        )
    assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# Service 6 — get_invoice_for_shipment happy path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_invoice_for_shipment_returns_lines():
    handlers = [
        lambda r: setattr(r.scalar_one_or_none, "return_value", _make_shipment()),
        lambda r: setattr(r.scalar_one_or_none, "return_value", _make_invoice()),
        lambda r: setattr(r.scalars.return_value.all, "return_value", [_make_invoice_line()]),
        lambda r: setattr(r.scalar_one_or_none, "return_value", None),
    ]
    session = _make_service_session(handlers)

    resp = await invoice_service.get_invoice_for_shipment(1, session)

    assert resp.invoice_number == "INV-2026-00001"
    assert resp.bol_number == "AV26-0001"
    assert len(resp.lines) == 1
    assert resp.lines[0].line_total == 12500


# ---------------------------------------------------------------------------
# Service 7 — no invoice yet → 404
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_invoice_for_shipment_without_invoice_raises_404():
    from fastapi import HTTPException

    handlers = [
        lambda r: setattr(r.scalar_one_or_none, "return_value", _make_shipment()),
        lambda r: setattr(r.scalar_one_or_none, "return_value", None),
    ]
    session = _make_service_session(handlers)

    with pytest.raises(HTTPException) as exc:
        await invoice_service.get_invoice_for_shipment(1, session)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Unit — money arithmetic stays exact ×100, no float drift
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "quantity,unit_price,expected",
    [
        (100, 100, 100),        # 1.00 × 1.00 = 1.00
        (5000, 250, 12500),     # 50.00 × 2.50 = 125.00
        (333, 333, 1108),       # truncating division, deterministic
        (1, 1, 0),              # 0.01 × 0.01 rounds down to 0.00
        (0, 500, 0),
    ],
)
def test_line_total_is_exact_integer_math(quantity, unit_price, expected):
    assert invoice_service._line_total(quantity, unit_price) == expected


# ---------------------------------------------------------------------------
# Unit — invoice number is deterministic, and survives a junk date
# ---------------------------------------------------------------------------
def test_invoice_number_is_deterministic():
    assert invoice_service._invoice_number(_make_shipment(shipment_id=7)) == "INV-2026-00007"


@pytest.mark.parametrize("bad_date", ["", "not-a-date", None])
def test_invoice_number_falls_back_on_unparseable_date(bad_date):
    shipment = _make_shipment(shipment_id=42, shipment_date=bad_date)
    assert invoice_service._invoice_number(shipment) == "INV-0000-00042"


# ---------------------------------------------------------------------------
# Service 8 — line descriptions resolve through lot → product
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invoice_line_description_uses_product_and_lot():
    from app.models.inventory import InventoryLot
    from app.models.product import Product
    lot = InventoryLot()
    lot.id = 1
    lot.product_id = 5
    lot.lot_number = "LOT-0001"

    product = Product()
    product.id = 5
    product.name = "Steel Rod"

    handlers = [
        lambda r: setattr(r.scalar_one_or_none, "return_value", _make_shipment()),
        lambda r: setattr(r.scalar_one_or_none, "return_value", None),
        lambda r: setattr(r.scalars.return_value.all, "return_value", [_make_shipment_item()]),
        lambda r: setattr(r.scalars.return_value.all, "return_value", [lot]),
        lambda r: setattr(r.scalars.return_value.all, "return_value", [product]),
        lambda r: setattr(r.scalar_one_or_none, "return_value", None),
    ]
    session = _flushing_session(handlers)

    resp = await invoice_service.generate_invoice(
        1, _token_user(), session
    )

    assert resp.lines[0].description == "Steel Rod (lot LOT-0001)"


# ---------------------------------------------------------------------------
# Service 9 — the check-then-insert race resolves to 409, not a 500
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_generate_surfaces_409_not_500():
    """Two callers can both pass the existence check; the DB rejects the loser.

    `invoices.shipment_id` is UNIQUE, so the second commit raises IntegrityError. That must come
    back as the same 409 the sequential path returns.
    """
    from fastapi import HTTPException
    from sqlalchemy.exc import IntegrityError

    handlers = [
        lambda r: setattr(r.scalar_one_or_none, "return_value", _make_shipment()),
        lambda r: setattr(r.scalar_one_or_none, "return_value", None),  # no invoice yet — we race
        lambda r: setattr(r.scalars.return_value.all, "return_value", [_make_shipment_item()]),
        lambda r: setattr(r.scalars.return_value.all, "return_value", []),
    ]
    session = _flushing_session(handlers)
    session.commit = AsyncMock(
        side_effect=IntegrityError("INSERT INTO invoices", {}, Exception("duplicate key"))
    )
    session.rollback = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await invoice_service.generate_invoice(1, _token_user(), session)

    assert exc.value.status_code == 409
    assert session.rollback.await_count == 1
