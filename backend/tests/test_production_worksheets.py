"""Tests for the production-worksheet close surface (ACR-30).

Two layers, both database-free:

* **Router** — RBAC 403s, validation 422s and status codes, with the service patched.
* **Service** — the close protocol's branch logic against a fake `AsyncSession` that dispatches
  on the SQL construct it is handed.

The concurrency guarantee itself cannot be proven with mocks — that is
`tests/integration/test_worksheet_close_concurrency.py`, which runs against real Postgres.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.sql import Select, Update

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.inventory import InventoryLot
from app.models.product import Product
from app.models.production_worksheet import ProductionWorksheet, ProductionWorksheetLine
from app.schemas.auth import TokenUser
from app.schemas.production_worksheet import (
    WorksheetCloseLine,
    WorksheetCloseRequest,
    WorksheetCreate,
    WorksheetLineCreate,
    WorksheetResponse,
)
from app.services import production_worksheet_service as svc
from tests.conftest import _make_rbac_session, _override

BASE_URL = "http://test"
_CREATED_AT = datetime(2026, 7, 23, tzinfo=timezone.utc)

_ALL_PRIVS = (
    "production.worksheet.view",
    "production.worksheet.create",
    "production.worksheet.close",
)

_VALID_CREATE = {
    "work_order_id": None,
    "production_line": "LINE-1",
    "scheduled_date": "2026-07-23",
    "lines": [{"product_id": 5, "planned_quantity": 10000}],
}
_VALID_CLOSE = {"expected_version": 0, "lines": [{"line_id": 100, "actual_quantity": 6000}]}


# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _make_worksheet(ws_id=1, status="draft", version=0):
    ws = ProductionWorksheet()
    ws.id = ws_id
    ws.work_order_id = None
    ws.production_line = "LINE-1"
    ws.scheduled_date = "2026-07-23"
    ws.status = status
    ws.version = version
    ws.created_by = 1
    ws.created_at = _CREATED_AT
    ws.closed_at = None
    return ws


def _make_line(line_id=100, ws_id=1, product_id=5, planned=10000, actual=None):
    ln = ProductionWorksheetLine()
    ln.id = line_id
    ln.worksheet_id = ws_id
    ln.product_id = product_id
    ln.planned_quantity = planned
    ln.actual_quantity = actual
    return ln


def _make_lot(lot_id=1, product_id=5, qty=10000, status="in_storage"):
    lot = InventoryLot()
    lot.id = lot_id
    lot.product_id = product_id
    lot.lot_number = f"LOT-{lot_id:04d}"
    lot.storage_location = "A-01"
    lot.status = status
    lot.quantity_on_hand = qty
    lot.pallet_number = None
    return lot


def _make_product(product_id=5, name="Steel Rod"):
    p = Product()
    p.id = product_id
    p.name = name
    p.category = "raw"
    return p


def _entity_name(stmt) -> str:
    """Which table a SQLAlchemy construct targets — how the fake session dispatches."""
    if isinstance(stmt, Update):
        return stmt.table.name
    if isinstance(stmt, Select):
        return stmt.column_descriptions[0]["entity"].__tablename__
    return ""


class _FakeSession:
    """AsyncSession stand-in that answers by construct type rather than call order."""

    def __init__(self, worksheet=None, lines=(), lots=(), products=(), claim_rowcount=1):
        self.worksheet = worksheet
        self.lines = list(lines)
        self.lots = list(lots)
        self.products = list(products)
        self.claim_rowcount = claim_rowcount
        self.added = []
        self.committed = False
        self.rolled_back = False
        self.claims = 0

    async def execute(self, stmt, *args, **kwargs):
        result = MagicMock()
        name = _entity_name(stmt)

        if isinstance(stmt, Update) and name == "production_worksheets":
            self.claims += 1
            result.rowcount = self.claim_rowcount
            return result

        if name == "production_worksheets":
            result.scalar_one_or_none.return_value = self.worksheet
        elif name == "production_worksheet_lines":
            result.scalars.return_value.all.return_value = list(self.lines)
        elif name == "inventory_lots":
            result.scalars.return_value.all.return_value = list(self.lots)
        elif name == "products":
            result.scalars.return_value.all.return_value = list(self.products)
        return result

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        """Stand in for the DB assigning PKs and server defaults on pending rows."""
        for obj in self.added:
            if isinstance(obj, ProductionWorksheet):
                if obj.id is None:
                    obj.id = 1
                if obj.created_at is None:
                    obj.created_at = _CREATED_AT
                if obj.version is None:
                    obj.version = 0
                self.worksheet = obj

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    def consume_txns(self):
        from app.models.inventory import InventoryTransaction

        return [o for o in self.added if isinstance(o, InventoryTransaction)]


def _user(user_id=1) -> TokenUser:
    return TokenUser(
        user_id=user_id,
        full_name="Test User",
        roles=["production_supervisor"],
        preferred_language="en",
        effective_privileges=list(_ALL_PRIVS),
        production_line="LINE-1",
    )


def _mock_response(status="draft", version=0) -> WorksheetResponse:
    return WorksheetResponse(
        id=1,
        work_order_id=None,
        production_line="LINE-1",
        scheduled_date="2026-07-23",
        status=status,
        version=version,
        created_by=1,
        created_at=_CREATED_AT,
        closed_at=None,
        lines=[],
    )


# ===========================================================================
# Router — status codes, RBAC, validation
# ===========================================================================


@pytest.mark.asyncio
async def test_create_worksheet_returns_201():
    """Case 1 — valid body with production.worksheet.create → 201, version 0."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=_ALL_PRIVS)

    with patch.object(svc, "create_worksheet", new=AsyncMock(return_value=_mock_response())):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.post(
                    "/api/v1/production-worksheets",
                    json=_VALID_CREATE,
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 201
            assert resp.json()["version"] == 0
            assert resp.json()["status"] == "draft"
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_create_worksheet_without_privilege_returns_403():
    """Case 2 — machine_operator holds no production.worksheet.* privilege."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("work_orders.view",))

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
            resp = await c.post(
                "/api/v1/production-worksheets",
                json=_VALID_CREATE,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
        assert "production.worksheet.create" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_create_worksheet_no_auth_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
        resp = await c.post("/api/v1/production-worksheets", json=_VALID_CREATE)
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,reason",
    [
        ({**_VALID_CREATE, "lines": []}, "empty lines"),
        ({**_VALID_CREATE, "lines": [{"product_id": 5, "planned_quantity": 0}]}, "zero qty"),
        ({**_VALID_CREATE, "lines": [{"product_id": 5, "planned_quantity": -100}]}, "negative qty"),
        ({"production_line": "LINE-1"}, "lines missing"),
    ],
)
async def test_create_worksheet_validation_returns_422(body, reason):
    """Cases 3-4 — Pydantic rejects malformed create bodies before the service runs."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=_ALL_PRIVS)

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
            resp = await c.post(
                "/api/v1/production-worksheets",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 422, f"{reason} should be rejected"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_worksheet_returns_200():
    """Case 5."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=_ALL_PRIVS)

    with patch.object(svc, "get_worksheet", new=AsyncMock(return_value=_mock_response())):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.get(
                    "/api/v1/production-worksheets/1",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["id"] == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_worksheet_missing_returns_404():
    """Case 6."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=_ALL_PRIVS)
    boom = HTTPException(status_code=404, detail="Production worksheet not found")

    with patch.object(svc, "get_worksheet", new=AsyncMock(side_effect=boom)):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.get(
                    "/api/v1/production-worksheets/999",
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_get_worksheet_without_privilege_returns_403():
    """Case 7."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("work_orders.view",))

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
            resp = await c.get(
                "/api/v1/production-worksheets/1",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_close_worksheet_returns_200():
    """Case 8 — happy path through the router."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=_ALL_PRIVS)

    with patch.object(
        svc, "close_worksheet", new=AsyncMock(return_value=_mock_response("closed", 1))
    ):
        app.dependency_overrides[get_db] = _override(session)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
                resp = await c.post(
                    "/api/v1/production-worksheets/1/close",
                    json=_VALID_CLOSE,
                    headers={"Authorization": f"Bearer {token}"},
                )
            assert resp.status_code == 200
            assert resp.json()["status"] == "closed"
            assert resp.json()["version"] == 1
        finally:
            app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_close_worksheet_without_privilege_returns_403():
    """Case 9 — blocked at the API, not merely hidden in the UI."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=("production.worksheet.view",))

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
            resp = await c.post(
                "/api/v1/production-worksheets/1/close",
                json=_VALID_CLOSE,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
        assert "production.worksheet.close" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,reason",
    [
        ({"expected_version": 0, "lines": [{"line_id": 100, "actual_quantity": -5}]}, "negative"),
        ({"expected_version": 0, "lines": []}, "empty lines"),
        ({"lines": [{"line_id": 100, "actual_quantity": 10}]}, "version missing"),
        ({"expected_version": -1, "lines": [{"line_id": 1, "actual_quantity": 10}]}, "neg version"),
    ],
)
async def test_close_worksheet_validation_returns_422(body, reason):
    """Case 13 — malformed close bodies never reach the protocol."""
    token = create_access_token(user_id=1)
    session = _make_rbac_session(privileges=_ALL_PRIVS)

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as c:
            resp = await c.post(
                "/api/v1/production-worksheets/1/close",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 422, f"{reason} should be rejected"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ===========================================================================
# Service — the close protocol's branch logic
# ===========================================================================


@pytest.mark.asyncio
async def test_service_create_worksheet_persists_lines():
    ws = _make_worksheet()
    session = _FakeSession(worksheet=ws, lines=[_make_line()], products=[_make_product()])
    body = WorksheetCreate(
        production_line="LINE-1",
        scheduled_date="2026-07-23",
        lines=[WorksheetLineCreate(product_id=5, planned_quantity=10000)],
    )

    # The worksheet the service constructs is not the fake's; capture what it adds.
    resp = await svc.create_worksheet(db=session, body=body, current_user=_user())

    assert session.committed is True
    added_lines = [o for o in session.added if isinstance(o, ProductionWorksheetLine)]
    assert len(added_lines) == 1
    assert added_lines[0].planned_quantity == 10000
    assert resp.status == "draft"


@pytest.mark.asyncio
async def test_service_get_worksheet_missing_raises_404():
    session = _FakeSession(worksheet=None)
    with pytest.raises(HTTPException) as exc:
        await svc.get_worksheet(db=session, worksheet_id=999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_service_close_missing_worksheet_raises_404():
    """Case 15."""
    session = _FakeSession(worksheet=None)
    body = WorksheetCloseRequest(
        expected_version=0, lines=[WorksheetCloseLine(line_id=100, actual_quantity=100)]
    )
    with pytest.raises(HTTPException) as exc:
        await svc.close_worksheet(db=session, worksheet_id=999, body=body, current_user=_user())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_service_close_stale_version_raises_409():
    """Case 10 — the conditional UPDATE matched no row, and the worksheet is still open."""
    ws = _make_worksheet(version=3)
    session = _FakeSession(
        worksheet=ws, lines=[_make_line()], lots=[_make_lot()], claim_rowcount=0
    )
    body = WorksheetCloseRequest(
        expected_version=0, lines=[WorksheetCloseLine(line_id=100, actual_quantity=100)]
    )

    with pytest.raises(HTTPException) as exc:
        await svc.close_worksheet(db=session, worksheet_id=1, body=body, current_user=_user())

    assert exc.value.status_code == 409
    assert "modified by another operation" in exc.value.detail
    assert session.rolled_back is True
    assert session.consume_txns() == [], "no stock may move when the claim fails"


@pytest.mark.asyncio
async def test_service_close_already_closed_raises_409():
    """Case 11 — distinguishable message from the stale-version case."""
    ws = _make_worksheet(status="closed", version=1)
    session = _FakeSession(
        worksheet=ws, lines=[_make_line()], lots=[_make_lot()], claim_rowcount=0
    )
    body = WorksheetCloseRequest(
        expected_version=1, lines=[WorksheetCloseLine(line_id=100, actual_quantity=100)]
    )

    with pytest.raises(HTTPException) as exc:
        await svc.close_worksheet(db=session, worksheet_id=1, body=body, current_user=_user())

    assert exc.value.status_code == 409
    assert "already closed" in exc.value.detail
    assert session.consume_txns() == []


@pytest.mark.asyncio
async def test_service_close_insufficient_stock_raises_409():
    """Case 12 — availability shortfall is a 409, never a negative on-hand."""
    ws = _make_worksheet()
    session = _FakeSession(
        worksheet=ws, lines=[_make_line()], lots=[_make_lot(qty=500)], products=[_make_product()]
    )
    body = WorksheetCloseRequest(
        expected_version=0, lines=[WorksheetCloseLine(line_id=100, actual_quantity=9000)]
    )

    with pytest.raises(HTTPException) as exc:
        await svc.close_worksheet(db=session, worksheet_id=1, body=body, current_user=_user())

    assert exc.value.status_code == 409
    assert "Insufficient stock" in exc.value.detail
    assert session.rolled_back is True
    assert session.committed is False


@pytest.mark.asyncio
async def test_service_close_unknown_line_raises_422():
    """Case 14 — a line_id from another worksheet."""
    ws = _make_worksheet()
    session = _FakeSession(worksheet=ws, lines=[_make_line(line_id=100)])
    body = WorksheetCloseRequest(
        expected_version=0, lines=[WorksheetCloseLine(line_id=777, actual_quantity=10)]
    )

    with pytest.raises(HTTPException) as exc:
        await svc.close_worksheet(db=session, worksheet_id=1, body=body, current_user=_user())

    assert exc.value.status_code == 422
    assert "does not belong" in exc.value.detail
    assert session.claims == 0, "the claim must not run on a malformed request"


@pytest.mark.asyncio
async def test_service_close_duplicate_line_raises_422():
    ws = _make_worksheet()
    session = _FakeSession(worksheet=ws, lines=[_make_line(line_id=100)])
    body = WorksheetCloseRequest(
        expected_version=0,
        lines=[
            WorksheetCloseLine(line_id=100, actual_quantity=10),
            WorksheetCloseLine(line_id=100, actual_quantity=20),
        ],
    )

    with pytest.raises(HTTPException) as exc:
        await svc.close_worksheet(db=session, worksheet_id=1, body=body, current_user=_user())

    assert exc.value.status_code == 422
    assert "more than once" in exc.value.detail


@pytest.mark.asyncio
async def test_service_close_happy_path_draws_fifo():
    """Consumes across lots oldest-id first and bumps the version exactly once."""
    ws = _make_worksheet()
    lots = [_make_lot(lot_id=1, qty=4000), _make_lot(lot_id=2, qty=5000)]
    session = _FakeSession(
        worksheet=ws, lines=[_make_line()], lots=lots, products=[_make_product()]
    )
    body = WorksheetCloseRequest(
        expected_version=0, lines=[WorksheetCloseLine(line_id=100, actual_quantity=6000)]
    )

    resp = await svc.close_worksheet(db=session, worksheet_id=1, body=body, current_user=_user())

    assert resp.status == "closed"
    assert resp.version == 1
    assert session.committed is True
    # FIFO: lot 1 drained, remainder off lot 2
    assert lots[0].quantity_on_hand == 0
    assert lots[0].status == "consumed"
    assert lots[1].quantity_on_hand == 3000
    assert lots[1].status == "in_storage"


@pytest.mark.asyncio
async def test_service_close_writes_only_consume_movements():
    """§7.1 — the `actual − planned` delta is computed, never written as a movement.

    planned 10000, actual 6000 → a 4000 delta exists as a reporting figure. If it were also
    written as an adjustment the ledger would double-count. Asserted on movement *kind and
    count*, not just the resulting total, because a compensating pair of rows nets to the right
    number while still being wrong.
    """
    ws = _make_worksheet()
    lots = [_make_lot(lot_id=1, qty=10000)]
    session = _FakeSession(
        worksheet=ws, lines=[_make_line(planned=10000)], lots=lots, products=[_make_product()]
    )
    body = WorksheetCloseRequest(
        expected_version=0, lines=[WorksheetCloseLine(line_id=100, actual_quantity=6000)]
    )

    await svc.close_worksheet(db=session, worksheet_id=1, body=body, current_user=_user())

    txns = session.consume_txns()
    assert len(txns) == 1, "exactly one movement per lot drawn from"
    assert txns[0].transaction_type == "consume"
    assert txns[0].quantity == -6000, "the consume is already at actual — nothing to adjust"
    assert txns[0].reference_type == "production_worksheet"
    assert txns[0].reference_id == 1
    assert [t for t in txns if t.transaction_type == "adjust"] == []
    assert lots[0].quantity_on_hand == 4000


@pytest.mark.asyncio
async def test_service_close_zero_actual_consumes_nothing():
    """A line that consumed nothing is legal and must move no stock."""
    ws = _make_worksheet()
    lots = [_make_lot(lot_id=1, qty=10000)]
    session = _FakeSession(
        worksheet=ws, lines=[_make_line()], lots=lots, products=[_make_product()]
    )
    body = WorksheetCloseRequest(
        expected_version=0, lines=[WorksheetCloseLine(line_id=100, actual_quantity=0)]
    )

    resp = await svc.close_worksheet(db=session, worksheet_id=1, body=body, current_user=_user())

    assert resp.status == "closed"
    assert session.consume_txns() == []
    assert lots[0].quantity_on_hand == 10000
