"""
Tests for T10 — Work Order CRUD API.
Expected: 18 passed, 0 failed.
All tests run without a live database connection.
"""
from datetime import date, datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.user import User
from app.models.work_order import WorkOrder, WorkOrderMaterial
from tests.conftest import _make_session, _override

BASE_URL = "http://test"

PRIVS_VIEW = ["work_orders.view"]
PRIVS_CREATE = ["work_orders.view", "work_orders.create"]
PRIVS_ASSIGN = ["work_orders.view", "work_orders.assign"]
PRIVS_STATUS = ["work_orders.view", "work_orders.status_update"]
PRIVS_SEQ = ["work_orders.view", "work_orders.sequence"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(production_line: str | None = None) -> User:
    u = User()
    u.id = 1
    u.username = "admin"
    u.full_name = "Admin User"
    u.preferred_language = "en"
    u.status = "active"
    u.production_line = production_line
    from app.core.security import hash_password
    u.password_hash = hash_password("password123")
    return u


def _make_wo(
    id: int = 1,
    product: str = "Widget A",
    status: str = "created",
    priority: str = "medium",
    display_sequence: int = 0,
    production_line: str | None = None,
    quantity_required: float = 10.0,
    quantity_produced: float = 0.0,
    target_date: date = date(2026, 5, 1),
) -> WorkOrder:
    wo = WorkOrder()
    wo.id = id
    wo.product = product
    wo.status = status
    wo.priority = priority
    wo.display_sequence = display_sequence
    wo.production_line = production_line
    wo.quantity_required = quantity_required
    wo.quantity_produced = quantity_produced
    wo.target_date = target_date
    wo.created_by = 1
    wo.created_at = datetime.now(timezone.utc)
    wo.updated_at = datetime.now(timezone.utc)
    return wo


def _make_material(id: int = 1, wo_id: int = 1) -> WorkOrderMaterial:
    m = WorkOrderMaterial()
    m.id = id
    m.work_order_id = wo_id
    m.material_type = "Steel"
    m.quantity_required = 5.0
    m.quantity_allocated = 0.0
    return m


_VALID_CREATE = {
    "product": "Widget A",
    "quantity_required": 10.0,
    "priority": "medium",
    "target_date": "2026-05-01",
    "materials": [{"material_type": "Steel", "quantity_required": 5.0}],
}


# ---------------------------------------------------------------------------
# POST /work-orders
# ---------------------------------------------------------------------------

async def test_create_work_order_success():
    """POST returns 201 when no duplicate and materials are available."""
    user = _make_user()

    def h_dup(r): r.scalar_one_or_none.return_value = None
    def h_qty(r): r.all.return_value = [("Steel", 100.0)]

    session = _make_session(user, ["company_admin"], PRIVS_CREATE, [h_dup, h_qty])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/work-orders",
                headers={"Authorization": f"Bearer {token}"},
                json=_VALID_CREATE,
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "created"
        assert "wo_number" in body
        assert "material_availability" in body
        assert body["material_availability"][0]["material_type"] == "Steel"
        assert body["material_availability"][0]["sufficient"] is True
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_create_work_order_hard_block_zero_availability():
    """POST returns 422 when a material has zero available quantity."""
    user = _make_user()

    def h_dup(r): r.scalar_one_or_none.return_value = None
    def h_qty(r): r.all.return_value = [("Steel", 0.0)]

    session = _make_session(user, ["company_admin"], PRIVS_CREATE, [h_dup, h_qty])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/work-orders",
                headers={"Authorization": f"Bearer {token}"},
                json=_VALID_CREATE,
            )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_create_work_order_duplicate_returns_409():
    """POST returns 409 when a duplicate WO exists and force=false."""
    user = _make_user()
    existing = _make_wo()

    def h_dup(r): r.scalar_one_or_none.return_value = existing

    session = _make_session(user, ["company_admin"], PRIVS_CREATE, [h_dup])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/work-orders",
                headers={"Authorization": f"Bearer {token}"},
                json=_VALID_CREATE,
            )
        assert resp.status_code == 409
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /work-orders
# ---------------------------------------------------------------------------

async def test_list_work_orders_returns_200():
    """GET returns 200 with paginated work orders."""
    user = _make_user()
    wo = _make_wo()
    material = _make_material()

    def h_count(r): r.scalar.return_value = 1
    def h_wos(r): r.scalars.return_value.all.return_value = [wo]
    def h_mats(r): r.scalars.return_value.all.return_value = [material]

    session = _make_session(user, ["company_admin"], PRIVS_VIEW, [h_count, h_wos, h_mats])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/work-orders",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["results"]) == 1
        assert body["results"][0]["product"] == "Widget A"
        assert body["results"][0]["wo_number"] == "WO-0001"
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_list_work_orders_no_auth():
    """GET without auth returns 401 or 403."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get("/api/v1/work-orders")
    assert resp.status_code in (401, 403)


async def test_list_work_orders_machine_operator_filtered():
    """Machine operators see only WOs for their production line."""
    user = _make_user(production_line="Line A")
    wo = _make_wo(production_line="Line A")
    material = _make_material()

    def h_count(r): r.scalar.return_value = 1
    def h_wos(r): r.scalars.return_value.all.return_value = [wo]
    def h_mats(r): r.scalars.return_value.all.return_value = [material]

    session = _make_session(user, ["machine_operator"], PRIVS_VIEW, [h_count, h_wos, h_mats])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/work-orders",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["results"][0]["production_line"] == "Line A"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /work-orders/{id}
# ---------------------------------------------------------------------------

async def test_get_work_order_returns_200():
    """GET /{id} returns 200 with work order details."""
    user = _make_user()
    wo = _make_wo(production_line="Line A")
    material = _make_material()

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = [material]

    session = _make_session(user, ["company_admin"], PRIVS_VIEW, [h_wo, h_mats])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/work-orders/1",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 1
        assert body["wo_number"] == "WO-0001"
        assert len(body["materials"]) == 1
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_get_work_order_not_found():
    """GET /{id} returns 404 for unknown work order."""
    user = _make_user()

    def h_wo(r): r.scalar_one_or_none.return_value = None

    session = _make_session(user, ["company_admin"], PRIVS_VIEW, [h_wo])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/work-orders/999",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_get_work_order_machine_operator_wrong_line():
    """Machine operator gets 403 for a WO on a different production line."""
    user = _make_user(production_line="Line A")
    wo = _make_wo(production_line="Line B")

    def h_wo(r): r.scalar_one_or_none.return_value = wo

    session = _make_session(user, ["machine_operator"], PRIVS_VIEW, [h_wo])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/work-orders/1",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# PATCH /work-orders/{id}/assign
# ---------------------------------------------------------------------------

async def test_assign_work_order_no_capacity_warning():
    """PATCH /assign assigns line with no capacity warning when < 3 active orders."""
    user = _make_user()
    wo = _make_wo()

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_count(r): r.scalar.return_value = 1  # 1 active order — no warning
    def h_mats(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["production_supervisor"], PRIVS_ASSIGN, [h_wo, h_count, h_mats])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/assign",
                headers={"Authorization": f"Bearer {token}"},
                json={"production_line": "Line A"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["production_line"] == "Line A"
        assert body["capacity_warning"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_assign_work_order_capacity_warning():
    """PATCH /assign returns capacity_warning when line has >= 3 active orders."""
    user = _make_user()
    wo = _make_wo()

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_count(r): r.scalar.return_value = 3  # 3 active orders on line → warning
    def h_mats(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["production_supervisor"], PRIVS_ASSIGN, [h_wo, h_count, h_mats])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/assign",
                headers={"Authorization": f"Bearer {token}"},
                json={"production_line": "Line B"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["capacity_warning"] is not None
        assert "Line B" in body["capacity_warning"]
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_assign_work_order_not_found():
    """PATCH /assign returns 404 for unknown work order."""
    user = _make_user()

    def h_wo(r): r.scalar_one_or_none.return_value = None

    session = _make_session(user, ["production_supervisor"], PRIVS_ASSIGN, [h_wo])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/999/assign",
                headers={"Authorization": f"Bearer {token}"},
                json={"production_line": "Line A"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# PATCH /work-orders/{id}/status
# ---------------------------------------------------------------------------

async def test_update_status_success():
    """PATCH /status updates work order status and returns 200."""
    user = _make_user()
    wo = _make_wo(status="created")

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["company_admin"], PRIVS_STATUS, [h_wo, h_mats])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/status",
                headers={"Authorization": f"Bearer {token}"},
                json={"status": "in_production"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "in_production"
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_update_status_completed_creates_finished_item():
    """PATCH /status to 'completed' triggers a db.add for a finished inventory item."""
    user = _make_user()
    wo = _make_wo(status="in_production", quantity_required=10.0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["company_admin"], PRIVS_STATUS, [h_wo, h_mats])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/status",
                headers={"Authorization": f"Bearer {token}"},
                json={"status": "completed", "quantity_produced": 10.0},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        add_calls = session.add.call_args_list
        from app.models.inventory import InventoryLot
        finished_lots = [
            c for c in add_calls
            if isinstance(c.args[0], InventoryLot)
        ]
        assert len(finished_lots) == 1
        lot = finished_lots[0].args[0]
        assert lot.lot_number == "WO-0001"
        assert lot.status == "in_storage"
        assert lot.quantity_on_hand == 1000  # 10.0 × 100
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_update_status_not_found():
    """PATCH /status returns 404 for unknown work order."""
    user = _make_user()

    def h_wo(r): r.scalar_one_or_none.return_value = None

    session = _make_session(user, ["company_admin"], PRIVS_STATUS, [h_wo])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/999/status",
                headers={"Authorization": f"Bearer {token}"},
                json={"status": "in_production"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# PATCH /work-orders/{id}/sequence
# ---------------------------------------------------------------------------

async def test_update_sequence_success():
    """PATCH /sequence updates display_sequence and returns 200."""
    user = _make_user()
    wo = _make_wo(display_sequence=0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["production_supervisor"], PRIVS_SEQ, [h_wo, h_mats])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/sequence",
                headers={"Authorization": f"Bearer {token}"},
                json={"display_sequence": 5},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["display_sequence"] == 5
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_update_sequence_not_found():
    """PATCH /sequence returns 404 for unknown work order."""
    user = _make_user()

    def h_wo(r): r.scalar_one_or_none.return_value = None

    session = _make_session(user, ["production_supervisor"], PRIVS_SEQ, [h_wo])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/999/sequence",
                headers={"Authorization": f"Bearer {token}"},
                json={"display_sequence": 3},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_update_sequence_no_auth():
    """PATCH /sequence without auth returns 401 or 403."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.patch(
            "/api/v1/work-orders/1/sequence",
            json={"display_sequence": 1},
        )
    assert resp.status_code in (401, 403)
