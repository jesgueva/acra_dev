"""
Integration tests — Scenarios 2 & 3: Work Order Lifecycle.

Scenario 2 (Happy Path): create WO → allocate → assign → advance status → complete.
Scenario 3 (Insufficient Materials): POST /work-orders → attempt allocate → 409.
"""
from datetime import date, datetime, timezone

from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.inventory import InventoryItem
from app.models.user import User
from app.models.work_order import WorkOrder, WorkOrderMaterial
from tests.conftest import _make_session, _override

BASE_URL = "http://test"

SUPERVISOR_PRIVS = [
    "work_orders.view",
    "work_orders.create",
    "work_orders.assign",
    "work_orders.allocate",
    "work_orders.status_update",
    "work_orders.sequence",
    "inventory.view",
]

_noop = lambda r: None  # noqa: E731  — absorbs SET TRANSACTION ISOLATION LEVEL


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_user(production_line: str | None = None) -> User:
    u = User()
    u.id = 1
    u.username = "supervisor"
    u.full_name = "Production Supervisor"
    u.preferred_language = "en"
    u.status = "active"
    u.production_line = production_line
    u.password_hash = hash_password("sup3rs3cr3t")
    return u


def _make_wo(
    id: int = 1,
    status: str = "created",
    product: str = "Widget A",
    quantity_required: float = 10.0,
    production_line: str | None = None,
) -> WorkOrder:
    wo = WorkOrder()
    wo.id = id
    wo.product = product
    wo.status = status
    wo.priority = "medium"
    wo.display_sequence = 0
    wo.production_line = production_line
    wo.quantity_required = quantity_required
    wo.quantity_produced = 0.0
    wo.target_date = date(2026, 5, 1)
    wo.created_by = 1
    wo.created_at = datetime.now(timezone.utc)
    wo.updated_at = datetime.now(timezone.utc)
    return wo


def _make_material(
    id: int = 1,
    material_type: str = "Steel",
    qty_required: float = 5.0,
    qty_allocated: float = 0.0,
) -> WorkOrderMaterial:
    m = WorkOrderMaterial()
    m.id = id
    m.work_order_id = 1
    m.material_type = material_type
    m.quantity_required = qty_required
    m.quantity_allocated = qty_allocated
    return m


def _make_inv_item(
    id: int = 10,
    material_type: str = "Steel",
    qty: float = 100.0,
    lot: str = "LOT-STEEL-001",
) -> InventoryItem:
    item = InventoryItem()
    item.id = id
    item.material_type = material_type
    item.category = "raw"
    item.quantity_on_hand = qty
    item.lot_batch_number = lot
    item.storage_location = "RACK-A"
    item.last_updated = datetime.now(timezone.utc)
    return item




_WO_CREATE_BODY = {
    "product": "Widget A",
    "quantity_required": 10.0,
    "priority": "medium",
    "target_date": "2026-05-01",
    "materials": [{"material_type": "Steel", "quantity_required": 5.0}],
}


# ---------------------------------------------------------------------------
# Scenario 2 — Work Order Lifecycle: Happy Path (5 chained steps)
# ---------------------------------------------------------------------------

async def test_wo_lifecycle_step1_create():
    """Step 1: POST /work-orders → 201 with status=created and availability shown."""
    user = _make_user()
    token = create_access_token(user_id=1)

    def h_dup(r): r.scalar_one_or_none.return_value = None
    def h_qty(r): r.all.return_value = [("Steel", 100.0)]

    session = _make_session(user, ["production_supervisor"], SUPERVISOR_PRIVS, [h_dup, h_qty])

    # Track added objects so flush can assign IDs (simulating DB sequence)
    added_objects: list = []
    session.add = lambda obj: added_objects.append(obj)

    async def _flush():
        for obj in added_objects:
            if isinstance(obj, WorkOrder) and obj.id is None:
                obj.id = 1

    session.flush = _flush

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/work-orders",
                json=_WO_CREATE_BODY,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "created"
        assert body["wo_number"] == "WO-0001"
        avail = body["material_availability"][0]
        assert avail["material_type"] == "Steel"
        assert avail["available"] == 100.0
        assert avail["sufficient"] is True
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_wo_lifecycle_step2_allocate():
    """Step 2: PATCH /work-orders/1/allocate → 200 with status=materials_allocated."""
    user = _make_user()
    token = create_access_token(user_id=1)
    wo = _make_wo(status="created")
    mat = _make_material(qty_required=5.0)
    inv = _make_inv_item(qty=100.0)
    mat_after = _make_material(qty_allocated=5.0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]
    def h_inv(r): r.scalars.return_value.all.return_value = [inv]
    def h_final(r): r.scalars.return_value.all.return_value = [mat_after]

    session = _make_session(
        user, ["production_supervisor"], SUPERVISOR_PRIVS,
        [_noop, h_wo, h_mats, h_inv, h_final],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/allocate",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "materials_allocated"
        assert body["materials"][0]["quantity_allocated"] == 5.0
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_wo_lifecycle_step3_assign():
    """Step 3: PATCH /work-orders/1/assign → 200 with production_line set."""
    user = _make_user()
    token = create_access_token(user_id=1)
    wo = _make_wo(status="materials_allocated")
    mat = _make_material(qty_allocated=5.0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_count(r): r.scalar.return_value = 0  # no other active orders on line
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]

    session = _make_session(
        user, ["production_supervisor"], SUPERVISOR_PRIVS,
        [h_wo, h_count, h_mats],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/assign",
                json={"production_line": "Line A"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["production_line"] == "Line A"
        assert body["capacity_warning"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_wo_lifecycle_step4_advance_to_in_production():
    """Step 4: PATCH /work-orders/1/status → in_production."""
    user = _make_user()
    token = create_access_token(user_id=1)
    wo = _make_wo(status="materials_allocated", production_line="Line A")
    mat = _make_material(qty_allocated=5.0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]

    session = _make_session(
        user, ["production_supervisor"], SUPERVISOR_PRIVS,
        [h_wo, h_mats],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/status",
                json={"status": "in_production"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "in_production"
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_wo_lifecycle_step5_complete():
    """Step 5: PATCH /work-orders/1/status → completed adds finished inventory item."""
    user = _make_user()
    token = create_access_token(user_id=1)
    wo = _make_wo(status="in_production", production_line="Line A", quantity_required=10.0)
    mat = _make_material(qty_allocated=5.0)

    added_objects = []

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]

    session = _make_session(
        user, ["production_supervisor"], SUPERVISOR_PRIVS,
        [h_wo, h_mats],
    )
    session.add = lambda obj: added_objects.append(obj)

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/status",
                json={"status": "completed", "quantity_produced": 10.0},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"

        # Verify finished inventory item was written
        finished = [o for o in added_objects if isinstance(o, InventoryItem) and o.category == "finished"]
        assert len(finished) == 1
        assert finished[0].material_type == "Widget A"
        assert float(finished[0].quantity_on_hand) == 10.0
        assert finished[0].storage_location == "FINISHED_GOODS"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Scenario 3 — Work Order Lifecycle: Insufficient Materials → 409
# ---------------------------------------------------------------------------

async def test_wo_lifecycle_create_with_low_stock_shows_insufficient():
    """Scenario 3a: Create WO when Steel stock is below required → sufficient=False."""
    user = _make_user()
    token = create_access_token(user_id=1)

    def h_dup(r): r.scalar_one_or_none.return_value = None
    def h_qty(r): r.all.return_value = [("Steel", 3.0)]  # only 3 available, need 5

    session = _make_session(user, ["production_supervisor"], SUPERVISOR_PRIVS, [h_dup, h_qty])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/work-orders",
                json=_WO_CREATE_BODY,
                headers={"Authorization": f"Bearer {token}"},
            )
        # WO is created but material_availability shows insufficient
        assert resp.status_code == 201
        avail = resp.json()["material_availability"][0]
        assert avail["sufficient"] is False
        assert avail["available"] == 3.0
        assert avail["required"] == 5.0
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_wo_lifecycle_allocate_insufficient_stock_returns_409():
    """Scenario 3b: Allocate when stock is insufficient → 409 Insufficient stock."""
    user = _make_user()
    token = create_access_token(user_id=1)
    wo = _make_wo(status="created")
    mat = _make_material(qty_required=10.0)  # need 10
    inv = _make_inv_item(qty=3.0)             # only 3 available

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]
    def h_inv(r): r.scalars.return_value.all.return_value = [inv]

    session = _make_session(
        user, ["production_supervisor"], SUPERVISOR_PRIVS,
        [_noop, h_wo, h_mats, h_inv],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/allocate",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 409
        assert "Insufficient stock" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_wo_lifecycle_create_hard_block_zero_stock_returns_422():
    """Scenario 3c: Create WO with zero available material → 422 hard block."""
    user = _make_user()
    token = create_access_token(user_id=1)

    def h_dup(r): r.scalar_one_or_none.return_value = None
    def h_qty(r): r.all.return_value = [("Steel", 0.0)]  # zero stock

    session = _make_session(user, ["production_supervisor"], SUPERVISOR_PRIVS, [h_dup, h_qty])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/work-orders",
                json=_WO_CREATE_BODY,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)
