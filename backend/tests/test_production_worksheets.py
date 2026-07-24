"""
Tests for ACR-30 — Production Worksheets API (create / get / concurrency-safe close).

Mocked-session unit layer: no live database. The lost-update guarantee itself is proven against
real PostgreSQL in ``tests/integration/test_worksheet_close_concurrency.py`` (TC-02) — these tests
cover the surface: status codes, RBAC, validation, and the failure modes the close must report.

Every ``require_privilege`` dependency burns execute calls 0-2 (user, roles, privileges); service
queries start at index 3. See CLAUDE.md "Authenticated endpoint mocks".
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.inventory import InventoryLot, InventoryTransaction
from app.models.product import Product
from app.models.production_worksheet import ProductionWorksheet, ProductionWorksheetLine
from tests.conftest import _make_session, _make_user, _override

BASE_URL = "http://test"
_URL = "/api/v1/production-worksheets"
_CREATED_AT = datetime(2026, 7, 23, tzinfo=timezone.utc)

_ALL_PRIVILEGES = (
    "production.worksheet.view",
    "production.worksheet.create",
    "production.worksheet.close",
)

_VALID_CREATE = {
    "production_line": "LINE-A",
    "scheduled_date": "2026-07-24",
    "lines": [{"product_id": 5, "planned_quantity": 6000}],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_product(product_id=5, name="Steel Rod"):
    p = Product()
    p.id = product_id
    p.name = name
    p.category = "raw"
    return p


def _make_lot(lot_id=1, product_id=5, quantity_on_hand=10000, status="in_storage"):
    lot = InventoryLot()
    lot.id = lot_id
    lot.product_id = product_id
    lot.lot_number = f"LOT-{lot_id:04d}"
    lot.storage_location = "A-01"
    lot.status = status
    lot.quantity_on_hand = quantity_on_hand
    lot.pallet_number = None
    return lot


def _make_worksheet(ws_id=1, status="draft", version=0, closed_at=None):
    ws = ProductionWorksheet()
    ws.id = ws_id
    ws.work_order_id = None
    ws.production_line = "LINE-A"
    ws.scheduled_date = "2026-07-24"
    ws.status = status
    ws.version = version
    ws.created_by = 1
    ws.created_at = _CREATED_AT
    ws.closed_at = closed_at
    return ws


def _make_line(line_id=10, ws_id=1, product_id=5, planned=6000, actual=None):
    line = ProductionWorksheetLine()
    line.id = line_id
    line.worksheet_id = ws_id
    line.product_id = product_id
    line.planned_quantity = planned
    line.actual_quantity = actual
    return line


def _scalars_all(items):
    """Handler for a query consumed via ``.scalars().all()``."""

    def _handler(result):
        result.scalars.return_value.all.return_value = items

    return _handler


def _scalar_one(obj):
    """Handler for a query consumed via ``.scalar_one_or_none()``."""

    def _handler(result):
        result.scalar_one_or_none.return_value = obj

    return _handler


def _session(privileges=_ALL_PRIVILEGES, handlers=None, roles=("company_admin",)):
    """Mock session with the 3 RBAC queries wired and ``flush`` populating server defaults.

    A real PostgreSQL flush returns the generated ``id`` and ``created_at`` (SQLAlchemy 2.0 fetches
    server defaults via RETURNING). The mock has to do the same or the response model fails to
    validate on fields the database would have filled.
    """
    user = _make_user()
    session = _make_session(user, list(roles), list(privileges), service_handlers=handlers or [])

    added: list = []
    session.add = MagicMock(side_effect=added.append)

    next_id = {"n": 100}

    async def _flush():
        for obj in added:
            if getattr(obj, "id", None) is None:
                next_id["n"] += 1
                obj.id = next_id["n"]
            if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
                obj.created_at = _CREATED_AT

    session.flush = AsyncMock(side_effect=_flush)
    session.added = added
    return session


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL)


def _auth() -> dict:
    return {"Authorization": f"Bearer {create_access_token(user_id=1)}"}


# ---------------------------------------------------------------------------
# 1-4 — create
# ---------------------------------------------------------------------------


async def test_create_worksheet_returns_201_with_version_zero():
    session = _session(handlers=[_scalars_all([_make_product()])])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(_URL, json=_VALID_CREATE, headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    assert body["version"] == 0
    assert body["production_line"] == "LINE-A"
    assert len(body["lines"]) == 1
    assert body["lines"][0]["product_id"] == 5
    assert body["lines"][0]["planned_quantity"] == 6000
    assert body["lines"][0]["product_name"] == "Steel Rod"
    assert body["lines"][0]["actual_quantity"] is None
    session.commit.assert_awaited()


async def test_create_worksheet_without_privilege_is_403():
    """machine_operator holds no production.worksheet.* privilege (migration 010)."""
    session = _session(privileges=("work_orders.view",), roles=("machine_operator",))
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(_URL, json=_VALID_CREATE, headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 403
    assert "production.worksheet.create" in resp.json()["detail"]


async def test_create_worksheet_with_no_lines_is_422():
    session = _session()
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(
                _URL, json={**_VALID_CREATE, "lines": []}, headers=_auth()
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 422


async def test_create_worksheet_with_non_positive_planned_quantity_is_422():
    # A fresh session per request: _make_session counts execute calls per session, so reusing one
    # across two requests would leave the second request's RBAC lookup reading past the end.
    for bad in (0, -100):
        app.dependency_overrides[get_db] = _override(_session())
        try:
            async with _client() as client:
                resp = await client.post(
                    _URL,
                    json={**_VALID_CREATE, "lines": [{"product_id": 5, "planned_quantity": bad}]},
                    headers=_auth(),
                )
        finally:
            app.dependency_overrides.pop(get_db, None)
        assert resp.status_code == 422, f"planned_quantity={bad} should be rejected"


async def test_create_worksheet_with_unknown_product_is_422():
    """The FK would raise IntegrityError → 500; the service checks first and reports 422."""
    session = _session(handlers=[_scalars_all([])])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(_URL, json=_VALID_CREATE, headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 422
    assert "Unknown product_id(s): [5]" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 5-7 — get
# ---------------------------------------------------------------------------


async def test_get_worksheet_returns_200():
    session = _session(
        handlers=[
            _scalar_one(_make_worksheet()),
            _scalars_all([_make_line()]),
            _scalars_all([_make_product()]),
        ]
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.get(f"{_URL}/1", headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == 1
    assert body["status"] == "draft"
    assert body["version"] == 0
    assert body["lines"][0]["product_name"] == "Steel Rod"


async def test_get_worksheet_missing_is_404():
    session = _session(handlers=[_scalar_one(None)])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.get(f"{_URL}/999", headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Production worksheet not found"


async def test_get_worksheet_without_privilege_is_403():
    session = _session(privileges=("work_orders.view",), roles=("machine_operator",))
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.get(f"{_URL}/1", headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 403
    assert "production.worksheet.view" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 8-15 — close
# ---------------------------------------------------------------------------


def _rowcount(n):
    """Handler for the optimistic-guard UPDATE, which is judged by rowcount alone."""

    def _handler(result):
        result.rowcount = n

    return _handler


_UNSET = object()  # lets a test pass worksheet=None to mean "no such worksheet"


def _close_session(
    worksheet=_UNSET,
    lines=None,
    guard_rowcount=1,
    lots=None,
    privileges=_ALL_PRIVILEGES,
    roles=("company_admin",),
):
    """Wire the close's query sequence: worksheet FOR UPDATE, lines, guard UPDATE, lots, products."""
    handlers = [
        _scalar_one(_make_worksheet() if worksheet is _UNSET else worksheet),
        _scalars_all([_make_line()] if lines is None else lines),
        _rowcount(guard_rowcount),
    ]
    if guard_rowcount == 1:
        handlers.append(_scalars_all([_make_lot()] if lots is None else lots))
        handlers.append(_scalars_all([_make_product()]))
    return _session(privileges=privileges, handlers=handlers, roles=roles)


_VALID_CLOSE = {"expected_version": 0, "lines": [{"line_id": 10, "actual_quantity": 6000}]}


async def test_close_worksheet_happy_path_consumes_stock():
    lot = _make_lot(quantity_on_hand=10000)
    session = _close_session(lots=[lot])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(f"{_URL}/1/close", json=_VALID_CLOSE, headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "closed"
    assert body["version"] == 1
    assert body["closed_at"] is not None
    assert body["lines"][0]["actual_quantity"] == 6000

    # Stock decremented by exactly the actual, once.
    assert lot.quantity_on_hand == 4000

    # Exactly one consume movement, and no compensating adjust row (plan §9.1).
    movements = [obj for obj in session.added if isinstance(obj, InventoryTransaction)]
    assert len(movements) == 1
    assert movements[0].transaction_type == "consume"
    assert movements[0].quantity == -6000
    assert movements[0].reference_type == "production_worksheet"
    assert movements[0].reference_id == 1
    assert [m for m in movements if m.transaction_type == "adjust"] == []
    session.commit.assert_awaited()


async def test_close_worksheet_without_privilege_is_403():
    session = _close_session(privileges=("production.worksheet.view",))
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(f"{_URL}/1/close", json=_VALID_CLOSE, headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 403
    assert "production.worksheet.close" in resp.json()["detail"]
    # Nothing was consumed on the way to the 403.
    assert [obj for obj in session.added if isinstance(obj, InventoryTransaction)] == []


async def test_close_worksheet_with_stale_version_is_409():
    """The guard UPDATE matched no row: another close already bumped the version."""
    session = _close_session(worksheet=_make_worksheet(version=1), guard_rowcount=0)
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(f"{_URL}/1/close", json=_VALID_CLOSE, headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 409
    assert "modified by another operation" in resp.json()["detail"]
    assert [obj for obj in session.added if isinstance(obj, InventoryTransaction)] == []
    session.rollback.assert_awaited()
    session.commit.assert_not_awaited()


async def test_close_worksheet_already_closed_is_409():
    session = _close_session(
        worksheet=_make_worksheet(status="closed", version=1), guard_rowcount=0
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(
                f"{_URL}/1/close",
                json={**_VALID_CLOSE, "expected_version": 1},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Worksheet is already closed."
    session.commit.assert_not_awaited()


async def test_close_worksheet_with_insufficient_stock_is_409():
    lot = _make_lot(quantity_on_hand=1000)  # need 6000
    session = _close_session(lots=[lot])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(f"{_URL}/1/close", json=_VALID_CLOSE, headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert "Insufficient stock for product 5" in detail
    assert "Required: 6000, available: 1000" in detail
    # Rolled back — the guard's status change is undone and the worksheet stays retryable.
    session.rollback.assert_awaited()
    session.commit.assert_not_awaited()


async def test_close_worksheet_with_negative_actual_quantity_is_422():
    session = _close_session()
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(
                f"{_URL}/1/close",
                json={"expected_version": 0, "lines": [{"line_id": 10, "actual_quantity": -5}]},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 422


async def test_close_worksheet_with_foreign_line_id_is_422():
    session = _close_session()
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(
                f"{_URL}/1/close",
                json={"expected_version": 0, "lines": [{"line_id": 999, "actual_quantity": 10}]},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 422
    assert "not on this worksheet: [999]" in resp.json()["detail"]


async def test_close_worksheet_with_duplicate_line_id_is_422():
    """Two entries for one line would double-consume inside a single serialized close."""
    session = _close_session()
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(
                f"{_URL}/1/close",
                json={
                    "expected_version": 0,
                    "lines": [
                        {"line_id": 10, "actual_quantity": 3000},
                        {"line_id": 10, "actual_quantity": 3000},
                    ],
                },
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 422
    assert "Duplicate line_id(s)" in resp.json()["detail"]
    assert [obj for obj in session.added if isinstance(obj, InventoryTransaction)] == []


async def test_close_worksheet_missing_a_line_is_422():
    """A partial close would leave a line unaccounted for and its stock never drawn."""
    session = _close_session(lines=[_make_line(line_id=10), _make_line(line_id=11, product_id=6)])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(f"{_URL}/1/close", json=_VALID_CLOSE, headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 422
    assert "missing line_id(s): [11]" in resp.json()["detail"]


async def test_close_worksheet_missing_worksheet_is_404():
    session = _close_session(worksheet=None)
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(f"{_URL}/999/close", json=_VALID_CLOSE, headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Production worksheet not found"


async def test_close_worksheet_with_zero_actual_records_no_movement():
    """A line that produced nothing closes cleanly and touches no stock."""
    lot = _make_lot(quantity_on_hand=10000)
    session = _close_session(lots=[lot])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(
                f"{_URL}/1/close",
                json={"expected_version": 0, "lines": [{"line_id": 10, "actual_quantity": 0}]},
                headers=_auth(),
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text
    assert resp.json()["lines"][0]["actual_quantity"] == 0
    assert lot.quantity_on_hand == 10000
    assert [obj for obj in session.added if isinstance(obj, InventoryTransaction)] == []


async def test_close_worksheet_draws_fifo_across_multiple_lots():
    """Need 6000 from lots of 2500 + 2500 + 5000 → drains the first two, part-draws the third."""
    lots = [
        _make_lot(lot_id=1, quantity_on_hand=2500),
        _make_lot(lot_id=2, quantity_on_hand=2500),
        _make_lot(lot_id=3, quantity_on_hand=5000),
    ]
    session = _close_session(lots=lots)
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with _client() as client:
            resp = await client.post(f"{_URL}/1/close", json=_VALID_CLOSE, headers=_auth())
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text
    assert [lot.quantity_on_hand for lot in lots] == [0, 0, 4000]

    movements = [obj for obj in session.added if isinstance(obj, InventoryTransaction)]
    assert [(m.lot_id, m.quantity) for m in movements] == [(1, -2500), (2, -2500), (3, -1000)]
    assert sum(-m.quantity for m in movements) == 6000
