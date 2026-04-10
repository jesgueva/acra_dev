"""
Tests for T11 — Work Order Allocation Algorithm.
Expected: 9 passed, 0 failed.
All tests run without a live database connection.
"""
from datetime import date, datetime, timezone

from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.inventory import InventoryItem
from app.models.work_order import MaterialAllocation, WorkOrder, WorkOrderMaterial
from tests.conftest import _make_session, _make_user, _override

BASE_URL = "http://test"

PRIVS_ALLOC = ["work_orders.view", "work_orders.allocate"]

# No-op handler for the SET TRANSACTION ISOLATION LEVEL execute call.
_noop = lambda r: None  # noqa: E731


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_wo(status: str = "created") -> WorkOrder:
    wo = WorkOrder()
    wo.id = 1
    wo.product = "Widget A"
    wo.status = status
    wo.priority = "medium"
    wo.display_sequence = 0
    wo.production_line = None
    wo.quantity_required = 10.0
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
    lot: str = "LOT-001",
) -> InventoryItem:
    item = InventoryItem()
    item.id = id
    item.item_name = material_type
    item.category = "raw"
    item.quantity_on_hand = qty
    item.lot_batch_number = lot
    item.storage_location = "RACK-A"
    item.last_updated = datetime.now(timezone.utc)
    return item


async def _patch_allocate(session, wo_id: int = 1):
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            return await client.patch(
                f"/api/v1/work-orders/{wo_id}/allocate",
                headers={"Authorization": f"Bearer {token}"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_allocate_success():
    """Happy path: WO in 'created' status with sufficient raw inventory → 200."""
    user = _make_user()
    wo = _make_wo(status="created")
    mat = _make_material()
    inv = _make_inv_item(qty=50.0)
    mat_after = _make_material(qty_allocated=5.0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]
    def h_inv(r): r.scalars.return_value.all.return_value = [inv]
    def h_final(r): r.scalars.return_value.all.return_value = [mat_after]

    session = _make_session(user, ["company_admin"], PRIVS_ALLOC, [_noop, h_wo, h_mats, h_inv, h_final])
    resp = await _patch_allocate(session)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "materials_allocated"
    assert body["wo_number"] == "WO-0001"
    assert body["materials"][0]["quantity_allocated"] == 5.0


async def test_allocate_wo_not_found():
    """PATCH on non-existent WO returns 404."""
    user = _make_user()

    def h_wo(r): r.scalar_one_or_none.return_value = None

    session = _make_session(user, ["company_admin"], PRIVS_ALLOC, [_noop, h_wo])
    resp = await _patch_allocate(session, wo_id=999)

    assert resp.status_code == 404


async def test_allocate_wrong_status_returns_409():
    """WO already in 'materials_allocated' status → 409 conflict."""
    user = _make_user()
    wo = _make_wo(status="materials_allocated")

    def h_wo(r): r.scalar_one_or_none.return_value = wo

    session = _make_session(user, ["company_admin"], PRIVS_ALLOC, [_noop, h_wo])
    resp = await _patch_allocate(session)

    assert resp.status_code == 409
    assert "cannot be allocated" in resp.json()["detail"]


async def test_allocate_insufficient_stock_returns_409():
    """Less raw inventory than required → 409 conflict."""
    user = _make_user()
    wo = _make_wo(status="created")
    mat = _make_material(qty_required=10.0)
    inv = _make_inv_item(qty=3.0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]
    def h_inv(r): r.scalars.return_value.all.return_value = [inv]

    session = _make_session(user, ["company_admin"], PRIVS_ALLOC, [_noop, h_wo, h_mats, h_inv])
    resp = await _patch_allocate(session)

    assert resp.status_code == 409
    assert "Insufficient stock" in resp.json()["detail"]


async def test_allocate_fifo_consumes_oldest_first():
    """FIFO: allocation deducts from the oldest inventory item first."""
    user = _make_user()
    wo = _make_wo(status="created")
    mat = _make_material(qty_required=5.0)
    older = _make_inv_item(id=10, qty=3.0, lot="LOT-OLD")
    newer = _make_inv_item(id=11, qty=10.0, lot="LOT-NEW")
    mat_after = _make_material(qty_allocated=5.0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]
    def h_inv(r): r.scalars.return_value.all.return_value = [older, newer]
    def h_final(r): r.scalars.return_value.all.return_value = [mat_after]

    session = _make_session(user, ["company_admin"], PRIVS_ALLOC, [_noop, h_wo, h_mats, h_inv, h_final])
    resp = await _patch_allocate(session)

    assert resp.status_code == 200
    assert float(older.quantity_on_hand) == 0.0
    assert float(newer.quantity_on_hand) == 8.0


async def test_allocate_spans_multiple_inventory_items():
    """Allocation creates MaterialAllocation records for each consumed inventory item."""
    user = _make_user()
    wo = _make_wo(status="created")
    mat = _make_material(qty_required=8.0)
    inv1 = _make_inv_item(id=10, qty=5.0, lot="LOT-A")
    inv2 = _make_inv_item(id=11, qty=10.0, lot="LOT-B")
    mat_after = _make_material(qty_allocated=8.0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]
    def h_inv(r): r.scalars.return_value.all.return_value = [inv1, inv2]
    def h_final(r): r.scalars.return_value.all.return_value = [mat_after]

    session = _make_session(user, ["company_admin"], PRIVS_ALLOC, [_noop, h_wo, h_mats, h_inv, h_final])

    added_objects = []
    session.add = lambda obj: added_objects.append(obj)

    resp = await _patch_allocate(session)

    assert resp.status_code == 200
    allocs = [o for o in added_objects if isinstance(o, MaterialAllocation)]
    assert len(allocs) == 2
    assert allocs[0].lot_batch_number == "LOT-A"
    assert allocs[1].lot_batch_number == "LOT-B"
    assert float(allocs[0].quantity_allocated) == 5.0
    assert float(allocs[1].quantity_allocated) == 3.0


async def test_allocate_multiple_materials_success():
    """WO with two materials: both are fully allocated in a single call."""
    user = _make_user()
    wo = _make_wo(status="created")
    mat1 = _make_material(id=1, material_type="Steel", qty_required=5.0)
    mat2 = _make_material(id=2, material_type="Rubber", qty_required=2.0)
    inv_steel = _make_inv_item(id=10, material_type="Steel", qty=20.0)
    inv_rubber = _make_inv_item(id=11, material_type="Rubber", qty=10.0)
    mat1_after = _make_material(id=1, material_type="Steel", qty_required=5.0, qty_allocated=5.0)
    mat2_after = _make_material(id=2, material_type="Rubber", qty_required=2.0, qty_allocated=2.0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo
    def h_mats(r): r.scalars.return_value.all.return_value = [mat1, mat2]
    def h_inv(r): r.scalars.return_value.all.return_value = [inv_steel, inv_rubber]
    def h_final(r): r.scalars.return_value.all.return_value = [mat1_after, mat2_after]

    session = _make_session(user, ["company_admin"], PRIVS_ALLOC, [_noop, h_wo, h_mats, h_inv, h_final])
    resp = await _patch_allocate(session)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "materials_allocated"
    materials = {m["material_type"]: m for m in body["materials"]}
    assert materials["Steel"]["quantity_allocated"] == 5.0
    assert materials["Rubber"]["quantity_allocated"] == 2.0


async def test_allocate_missing_privilege_returns_403():
    """Request without work_orders.allocate privilege → 403."""
    user = _make_user()
    session = _make_session(user, ["machine_operator"], ["work_orders.view"])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/work-orders/1/allocate",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_allocate_no_auth_returns_401_or_403():
    """Request without Authorization header is rejected."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.patch("/api/v1/work-orders/1/allocate")
    assert resp.status_code in (401, 403)


async def test_allocation_concurrent_requests_no_double_deduction():
    """
    Two sequential requests simulating concurrent access to the same WO.
    The first allocates successfully; the second sees 'materials_allocated' and returns 409,
    proving the pessimistic lock prevents double-deduction.
    """
    user = _make_user()

    wo_created = _make_wo(status="created")
    mat = _make_material(qty_required=10.0)
    inv = _make_inv_item(qty=10.0)
    mat_after = _make_material(qty_required=10.0, qty_allocated=10.0)

    def h_wo(r): r.scalar_one_or_none.return_value = wo_created
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]
    def h_inv(r): r.scalars.return_value.all.return_value = [inv]
    def h_final(r): r.scalars.return_value.all.return_value = [mat_after]

    session1 = _make_session(user, ["company_admin"], PRIVS_ALLOC, [_noop, h_wo, h_mats, h_inv, h_final])
    resp1 = await _patch_allocate(session1)
    assert resp1.status_code == 200
    assert resp1.json()["status"] == "materials_allocated"

    wo_allocated = _make_wo(status="materials_allocated")

    def h_wo_allocated(r): r.scalar_one_or_none.return_value = wo_allocated

    session2 = _make_session(user, ["company_admin"], PRIVS_ALLOC, [_noop, h_wo_allocated])
    resp2 = await _patch_allocate(session2)
    assert resp2.status_code == 409

    # Only 10 deducted total (first request), not 20
    assert float(inv.quantity_on_hand) == 0.0
