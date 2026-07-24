"""Tests for ACR-27 — reserved / available stock.

Service-level tests drive `reservation_service` directly against a mocked AsyncSession; HTTP
tests cover RBAC and request validation through the router. No live database.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.audit import AuditLog
from app.models.inventory import InventoryTransaction, LotStatus
from app.models.product import Product
from app.models.reservation import ReservationStatus, StockReservation
from app.schemas.reservation import ReservationCreate
from app.services import reservation_service
from tests.conftest import _make_session, _make_user, _override

BASE_URL = "http://test"
PRIVS_VIEW = ["inventory.view"]
PRIVS_RESERVE = ["inventory.view", "inventory.reserve"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product(id: int = 1, name: str = "Steel Rod") -> Product:
    p = Product()
    p.id = id
    p.name = name
    return p


def _make_reservation(
    id: int = 1,
    product_id: int = 1,
    state: str = "in_storage",
    quantity: int = 3000,
    status: str = "active",
    production_worksheet_line_id: int | None = None,
) -> StockReservation:
    r = StockReservation()
    r.id = id
    r.product_id = product_id
    r.state = state
    r.quantity = quantity
    r.production_worksheet_line_id = production_worksheet_line_id
    r.status = status
    r.created_by = 1
    r.created_at = datetime.now(timezone.utc)
    r.released_at = None
    return r


# -- result handlers, one per db.execute() call, in order --------------------

def _one(obj):
    """Handler for `.scalar_one_or_none()` lookups."""
    return lambda r: setattr(r.scalar_one_or_none, "return_value", obj)


def _scalar(value):
    """Handler for aggregate `.scalar()` reads."""
    return lambda r: setattr(r.scalar, "return_value", value)


def _all(objs):
    """Handler for `.scalars().all()` reads."""
    return lambda r: setattr(r.scalars.return_value.all, "return_value", list(objs))


def _noop():
    """Handler for a query whose result is discarded (e.g. the FOR UPDATE lock)."""
    return lambda r: None


def _svc_session(handlers):
    """Mock AsyncSession for calling a service directly (no RBAC queries).

    Records every query on `.queries` and every added object on `.added`; `flush()` assigns a PK
    and `created_at` the way a real flush would.
    """
    session = AsyncMock()
    calls = {"n": 0}
    added: list = []
    queries: list = []

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        queries.append(query)
        n = calls["n"]
        calls["n"] += 1
        if n < len(handlers):
            handlers[n](result)
        return result

    async def _flush():
        for obj in added:
            if isinstance(obj, StockReservation) and obj.id is None:
                obj.id = 99
                obj.created_at = datetime.now(timezone.utc)

    session.execute = _execute
    session.add = MagicMock(side_effect=added.append)
    session.flush = AsyncMock(side_effect=_flush)
    session.commit = AsyncMock()
    session.added = added
    session.queries = queries
    return session


def _sql(query) -> str:
    return str(query.compile(compile_kwargs={"literal_binds": True}))


# ===========================================================================
# Availability
# ===========================================================================

@pytest.mark.asyncio
async def test_availability_without_reservations_equals_on_hand():
    """Case 15 — no reservations: reserved is 0 and available tracks on-hand."""
    session = _svc_session([_one(_make_product()), _scalar(10000), _scalar(0)])

    result = await reservation_service.availability(
        db=session, product_id=1, state=LotStatus.IN_STORAGE
    )

    assert result.on_hand == 10000
    assert result.reserved == 0
    assert result.available == 10000
    assert result.product_name == "Steel Rod"


@pytest.mark.asyncio
async def test_availability_subtracts_active_reservations():
    """Case 16 — the core formula: available = on_hand − reserved."""
    session = _svc_session([_one(_make_product()), _scalar(10000), _scalar(3000)])

    result = await reservation_service.availability(
        db=session, product_id=1, state=LotStatus.IN_STORAGE
    )

    assert result.on_hand == 10000
    assert result.reserved == 3000
    assert result.available == 7000


@pytest.mark.asyncio
async def test_availability_reserved_query_counts_only_active():
    """Case 17 — released reservations must not count toward `reserved`."""
    session = _svc_session([_one(_make_product()), _scalar(10000), _scalar(0)])

    await reservation_service.availability(
        db=session, product_id=1, state=LotStatus.IN_STORAGE
    )

    reserved_sql = _sql(session.queries[2])
    assert "stock_reservations.status" in reserved_sql
    assert "'active'" in reserved_sql
    assert "'released'" not in reserved_sql


@pytest.mark.asyncio
async def test_availability_no_stock_returns_zeros():
    """Case 18 — a product with no lots and no reservations reports all zeros."""
    session = _svc_session([_one(_make_product()), _scalar(0), _scalar(0)])

    result = await reservation_service.availability(
        db=session, product_id=1, state=LotStatus.IN_STORAGE
    )

    assert (result.on_hand, result.reserved, result.available) == (0, 0, 0)


@pytest.mark.asyncio
async def test_availability_can_go_negative_and_is_not_clamped():
    """Case 19 — stock adjusted below active reservations leaves available negative."""
    session = _svc_session([_one(_make_product()), _scalar(1000), _scalar(4000)])

    result = await reservation_service.availability(
        db=session, product_id=1, state=LotStatus.IN_STORAGE
    )

    assert result.available == -3000


@pytest.mark.asyncio
async def test_availability_unknown_product_404():
    session = _svc_session([_one(None)])

    with pytest.raises(HTTPException) as exc:
        await reservation_service.availability(
            db=session, product_id=999, state=LotStatus.IN_STORAGE
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_availability_filters_on_hand_by_state():
    """On-hand is per (item, state) — the lot query must filter on the requested state."""
    session = _svc_session([_one(_make_product()), _scalar(500), _scalar(0)])

    await reservation_service.availability(
        db=session, product_id=1, state=LotStatus.IN_PRODUCTION
    )

    on_hand_sql = _sql(session.queries[1])
    assert "inventory_lots.status" in on_hand_sql
    assert "'in_production'" in on_hand_sql


# ===========================================================================
# Reserve
# ===========================================================================

@pytest.mark.asyncio
async def test_reserve_happy_path():
    """Case 1 — a reservation is created ACTIVE for the requested item/state/quantity."""
    session = _svc_session(
        [_one(_make_product()), _noop(), _scalar(10000), _scalar(0)]
    )

    result = await reservation_service.reserve(
        db=session,
        data=ReservationCreate(product_id=1, state=LotStatus.IN_STORAGE, quantity=4000),
        user_id=7,
    )

    assert result.id == 99
    assert result.product_id == 1
    assert result.quantity == 4000
    assert result.status == ReservationStatus.ACTIVE
    assert result.state == LotStatus.IN_STORAGE
    assert result.product_name == "Steel Rod"
    assert result.created_by == 7
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reserve_does_not_touch_on_hand():
    """Case 2 — THE acceptance criterion: no stock movement, no lot mutation.

    Reserving must add exactly one StockReservation and one AuditLog — never an
    InventoryTransaction, which is what would move on-hand.
    """
    session = _svc_session(
        [_one(_make_product()), _noop(), _scalar(10000), _scalar(0)]
    )

    await reservation_service.reserve(
        db=session,
        data=ReservationCreate(product_id=1, state=LotStatus.IN_STORAGE, quantity=4000),
        user_id=7,
    )

    assert not any(isinstance(o, InventoryTransaction) for o in session.added)
    assert len([o for o in session.added if isinstance(o, StockReservation)]) == 1
    assert len([o for o in session.added if isinstance(o, AuditLog)]) == 1
    assert len(session.added) == 2


@pytest.mark.asyncio
async def test_reserve_takes_row_lock_before_reading_available():
    """The FOR UPDATE guard must run before on-hand/reserved are read (D4)."""
    session = _svc_session(
        [_one(_make_product()), _noop(), _scalar(10000), _scalar(0)]
    )

    await reservation_service.reserve(
        db=session,
        data=ReservationCreate(product_id=1, state=LotStatus.IN_STORAGE, quantity=1000),
        user_id=7,
    )

    assert "FOR UPDATE" in _sql(session.queries[1])


@pytest.mark.asyncio
async def test_reserve_unknown_product_404():
    """Case 4."""
    session = _svc_session([_one(None)])

    with pytest.raises(HTTPException) as exc:
        await reservation_service.reserve(
            db=session,
            data=ReservationCreate(product_id=999, quantity=100),
            user_id=7,
        )

    assert exc.value.status_code == 404
    assert not session.added


@pytest.mark.asyncio
async def test_reserve_exceeding_available_422():
    """Case 8 — cannot reserve more than available; nothing is persisted."""
    session = _svc_session(
        [_one(_make_product()), _noop(), _scalar(10000), _scalar(8000)]
    )

    with pytest.raises(HTTPException) as exc:
        await reservation_service.reserve(
            db=session,
            data=ReservationCreate(product_id=1, quantity=2001),
            user_id=7,
        )

    assert exc.value.status_code == 422
    assert "20.01" in exc.value.detail   # requested
    assert "20.00" in exc.value.detail   # available
    assert not session.added
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_reserve_exactly_available_succeeds():
    """Case 9 — boundary: reserving the whole remaining availability is allowed."""
    session = _svc_session(
        [_one(_make_product()), _noop(), _scalar(10000), _scalar(6000)]
    )

    result = await reservation_service.reserve(
        db=session,
        data=ReservationCreate(product_id=1, quantity=4000),
        user_id=7,
    )

    assert result.quantity == 4000


@pytest.mark.asyncio
async def test_reserve_against_zero_available_422():
    """A product with no stock cannot be reserved against."""
    session = _svc_session([_one(_make_product()), _noop(), _scalar(0), _scalar(0)])

    with pytest.raises(HTTPException) as exc:
        await reservation_service.reserve(
            db=session,
            data=ReservationCreate(product_id=1, quantity=1),
            user_id=7,
        )

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_reserve_without_worksheet_line_is_null():
    """Case 10 — ACR-29 hasn't landed, so the worksheet line stays NULL."""
    session = _svc_session(
        [_one(_make_product()), _noop(), _scalar(10000), _scalar(0)]
    )

    result = await reservation_service.reserve(
        db=session,
        data=ReservationCreate(product_id=1, quantity=1000),
        user_id=7,
    )

    assert result.production_worksheet_line_id is None


@pytest.mark.asyncio
async def test_reserve_carries_worksheet_line_when_given():
    session = _svc_session(
        [_one(_make_product()), _noop(), _scalar(10000), _scalar(0)]
    )

    result = await reservation_service.reserve(
        db=session,
        data=ReservationCreate(
            product_id=1, quantity=1000, production_worksheet_line_id=42
        ),
        user_id=7,
    )

    assert result.production_worksheet_line_id == 42


@pytest.mark.asyncio
async def test_reserve_writes_audit_entry():
    session = _svc_session(
        [_one(_make_product()), _noop(), _scalar(10000), _scalar(0)]
    )

    await reservation_service.reserve(
        db=session,
        data=ReservationCreate(product_id=1, quantity=1000),
        user_id=7,
    )

    audit = next(o for o in session.added if isinstance(o, AuditLog))
    assert audit.action == "reservation.created"
    assert audit.entity_type == "stock_reservation"
    assert audit.user_id == 7


# ===========================================================================
# Release
# ===========================================================================

@pytest.mark.asyncio
async def test_release_happy_path():
    """Case 11 — status flips to released and released_at is stamped."""
    reservation = _make_reservation()
    session = _svc_session([_one(reservation), _all([_make_product()])])

    result = await reservation_service.release(db=session, reservation_id=1, user_id=7)

    assert result.status == ReservationStatus.RELEASED
    assert result.released_at is not None
    assert result.product_name == "Steel Rod"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_release_unknown_404():
    """Case 12."""
    session = _svc_session([_one(None)])

    with pytest.raises(HTTPException) as exc:
        await reservation_service.release(db=session, reservation_id=999, user_id=7)

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_release_already_released_422():
    """Case 13 — double-submit is surfaced, not silently swallowed."""
    session = _svc_session([_one(_make_reservation(status="released"))])

    with pytest.raises(HTTPException) as exc:
        await reservation_service.release(db=session, reservation_id=1, user_id=7)

    assert exc.value.status_code == 422
    assert "already released" in exc.value.detail
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_release_does_not_touch_on_hand():
    """Releasing returns quantity to available without writing a stock movement."""
    session = _svc_session([_one(_make_reservation()), _all([_make_product()])])

    await reservation_service.release(db=session, reservation_id=1, user_id=7)

    assert not any(isinstance(o, InventoryTransaction) for o in session.added)


@pytest.mark.asyncio
async def test_release_writes_audit_entry():
    session = _svc_session([_one(_make_reservation()), _all([_make_product()])])

    await reservation_service.release(db=session, reservation_id=1, user_id=7)

    audit = next(o for o in session.added if isinstance(o, AuditLog))
    assert audit.action == "reservation.released"
    assert audit.entity_type == "stock_reservation"


# ===========================================================================
# List
# ===========================================================================

@pytest.mark.asyncio
async def test_list_reservations_returns_paginated_results():
    """Case 22."""
    session = _svc_session(
        [_scalar(2), _all([_make_reservation(id=1), _make_reservation(id=2)]),
         _all([_make_product()])]
    )

    result = await reservation_service.list_reservations(db=session, page=1, page_size=50)

    assert result.total == 2
    assert len(result.results) == 2
    assert result.results[0].product_name == "Steel Rod"


@pytest.mark.asyncio
async def test_list_reservations_applies_filters():
    session = _svc_session([_scalar(0), _all([]), _all([])])

    await reservation_service.list_reservations(
        db=session,
        product_id=5,
        state=LotStatus.IN_PRODUCTION,
        status_filter=ReservationStatus.RELEASED,
    )

    sql = _sql(session.queries[1])
    assert "stock_reservations.product_id" in sql
    assert "'in_production'" in sql
    assert "'released'" in sql


@pytest.mark.asyncio
async def test_list_reservations_empty():
    session = _svc_session([_scalar(0), _all([]), _all([])])

    result = await reservation_service.list_reservations(db=session)

    assert result.total == 0
    assert result.results == []


# ===========================================================================
# HTTP — RBAC and request validation
# ===========================================================================

@pytest.mark.asyncio
async def test_reserve_requires_reserve_privilege_403():
    """Case 3 — inventory.view alone must not permit reserving."""
    session = _make_session(_make_user(), ["receiving_clerk"], PRIVS_VIEW)
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/reservations",
                json={"product_id": 1, "quantity": 100},
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 403
        assert "inventory.reserve" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_release_requires_reserve_privilege_403():
    """Case 14."""
    session = _make_session(_make_user(), ["receiving_clerk"], PRIVS_VIEW)
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/reservations/1/release",
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_list_reservations_requires_view_privilege_403():
    """Case 23."""
    session = _make_session(_make_user(), ["machine_operator"], ["work_orders.view"])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/reservations",
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_availability_requires_view_privilege_403():
    """Case 20."""
    session = _make_session(_make_user(), ["machine_operator"], ["work_orders.view"])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/inventory/availability?product_id=1",
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_reserve_without_auth_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.post(
            "/api/v1/reservations", json={"product_id": 1, "quantity": 100}
        )
    assert resp.status_code in (401, 403)


@pytest.mark.parametrize(
    "body,label",
    [
        ({"product_id": 1, "quantity": 0}, "zero"),
        ({"product_id": 1, "quantity": -500}, "negative"),
        ({"product_id": 1, "quantity": 100, "state": "floating"}, "bad state"),
        ({"quantity": 100}, "missing product_id"),
        ({"product_id": 1}, "missing quantity"),
        ({"product_id": "abc", "quantity": 100}, "non-numeric product_id"),
    ],
)
@pytest.mark.asyncio
async def test_reserve_rejects_invalid_bodies_422(body, label):
    """Cases 5, 6, 7 — validation happens before any service work."""
    session = _make_session(_make_user(), ["company_admin"], PRIVS_RESERVE)
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/reservations",
                json=body,
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 422, f"{label} should be rejected"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_availability_rejects_invalid_state_422():
    """Case 21."""
    session = _make_session(_make_user(), ["company_admin"], PRIVS_RESERVE)
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/inventory/availability?product_id=1&state=floating",
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_availability_requires_product_id_422():
    session = _make_session(_make_user(), ["company_admin"], PRIVS_RESERVE)
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/inventory/availability",
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_reserve_returns_201_through_the_router():
    """End-to-end through the router with the RBAC + service queries mocked."""
    session = _make_session(
        _make_user(),
        ["company_admin"],
        PRIVS_RESERVE,
        service_handlers=[
            _one(_make_product()),
            _noop(),
            _scalar(10000),
            _scalar(0),
        ],
    )
    # conftest's session lacks the flush-assigns-PK behaviour the response needs.
    added: list = []
    session.add = MagicMock(side_effect=added.append)

    async def _flush():
        for obj in added:
            if isinstance(obj, StockReservation) and obj.id is None:
                obj.id = 99
                obj.created_at = datetime.now(timezone.utc)

    session.flush = AsyncMock(side_effect=_flush)

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/reservations",
                json={"product_id": 1, "quantity": 4000},
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["quantity"] == 4000
        assert body["status"] == "active"
        assert body["state"] == "in_storage"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_release_returns_200_through_the_router():
    session = _make_session(
        _make_user(),
        ["company_admin"],
        PRIVS_RESERVE,
        service_handlers=[_one(_make_reservation()), _all([_make_product()])],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/reservations/1/release",
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "released"
        assert body["released_at"] is not None
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_list_returns_200_through_the_router():
    session = _make_session(
        _make_user(),
        ["company_admin"],
        PRIVS_RESERVE,
        service_handlers=[
            _scalar(1),
            _all([_make_reservation()]),
            _all([_make_product()]),
        ],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/reservations?product_id=1&status=active",
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["results"][0]["product_name"] == "Steel Rod"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_availability_returns_200_through_the_router():
    session = _make_session(
        _make_user(),
        ["company_admin"],
        PRIVS_RESERVE,
        service_handlers=[_one(_make_product()), _scalar(10000), _scalar(3000)],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/inventory/availability?product_id=1",
                headers={"Authorization": f"Bearer {create_access_token(user_id=1)}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "product_id": 1,
            "product_name": "Steel Rod",
            "state": "in_storage",
            "on_hand": 10000,
            "reserved": 3000,
            "available": 7000,
        }
    finally:
        app.dependency_overrides.pop(get_db, None)
