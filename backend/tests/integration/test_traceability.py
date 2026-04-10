"""
Integration tests — Scenario 4: Lot Traceability Chain.

Verifies that after a delivery is received and materials are allocated to a work order,
GET /inventory/trace/{lot} returns source delivery + allocation info.
"""
from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.delivery import Delivery, DeliveryItem
from app.models.inventory import InventoryItem
from app.models.user import User
from app.models.work_order import MaterialAllocation, WorkOrder, WorkOrderMaterial
from tests.conftest import _make_session, _override

BASE_URL = "http://test"
LOT = "LOT-TRACE-001"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_user() -> User:
    u = User()
    u.id = 1
    u.username = "admin"
    u.full_name = "Admin"
    u.preferred_language = "en"
    u.status = "active"
    u.production_line = None
    u.password_hash = hash_password("pw123")
    return u




def _make_inventory_item(source_delivery_item_id: int | None = 10) -> InventoryItem:
    inv = InventoryItem()
    inv.id = 100
    inv.item_name = "Steel Rod"
    inv.category = "raw"
    inv.quantity_on_hand = 30.0
    inv.lot_batch_number = LOT
    inv.storage_location = "RACK-A"
    inv.source_delivery_item_id = source_delivery_item_id
    inv.last_updated = datetime(2026, 1, 15, tzinfo=timezone.utc)
    return inv


def _make_delivery_item() -> DeliveryItem:
    di = DeliveryItem()
    di.id = 10
    di.delivery_id = 1
    di.material_type = "Steel Rod"
    di.quantity = 50.0
    di.lot_batch_number = LOT
    di.storage_location = "RACK-A"
    di.inventory_item_id = 100
    return di


def _make_delivery() -> Delivery:
    from datetime import date
    d = Delivery()
    d.id = 1
    d.supplier = "Acme Metals"
    d.carrier = "Fast Freight"
    d.delivery_date = date(2026, 1, 15)
    d.bol_reference = "BOL-2026-001"
    d.created_by = 1
    d.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
    return d


def _make_allocation() -> MaterialAllocation:
    a = MaterialAllocation()
    a.id = 1
    a.work_order_material_id = 1
    a.inventory_id = 100
    a.lot_batch_number = LOT
    a.quantity_allocated = 5.0
    a.allocated_at = datetime(2026, 1, 20, tzinfo=timezone.utc)
    return a


def _make_wom() -> WorkOrderMaterial:
    m = WorkOrderMaterial()
    m.id = 1
    m.work_order_id = 1
    m.material_type = "Steel Rod"
    m.quantity_required = 5.0
    m.quantity_allocated = 5.0
    return m


def _make_work_order() -> WorkOrder:
    from datetime import date
    wo = WorkOrder()
    wo.id = 1
    wo.product = "Widget A"
    wo.status = "materials_allocated"
    wo.priority = "medium"
    wo.display_sequence = 0
    wo.production_line = "Line A"
    wo.quantity_required = 10.0
    wo.quantity_produced = 0.0
    wo.target_date = date(2026, 5, 1)
    wo.created_by = 1
    wo.created_at = datetime(2026, 1, 18, tzinfo=timezone.utc)
    wo.updated_at = datetime(2026, 1, 20, tzinfo=timezone.utc)
    return wo


# ---------------------------------------------------------------------------
# Integration Test 1 — Full traceability chain with source delivery + WO
# ---------------------------------------------------------------------------

async def test_lot_traceability_chain_full():
    """
    Scenario 4: After delivery + allocation, trace/{lot} returns:
    - source_delivery with supplier & BOL
    - inventory_items with the lot
    - work_orders that consumed from this lot
    """
    user = _make_user()
    token = create_access_token(user_id=1)

    inv = _make_inventory_item(source_delivery_item_id=10)
    di = _make_delivery_item()
    delivery = _make_delivery()
    alloc = _make_allocation()
    wom = _make_wom()
    wo = _make_work_order()

    # trace_lot query sequence (RBAC at n=0,1,2 then service at n=3+):
    # n=3: items_res → scalars().all() = [inv]
    # n=4: di_res → scalar_one_or_none() = di  (because source_delivery_item_id is set)
    # n=5: d_res → scalar_one_or_none() = delivery
    # n=6: alloc_res → scalars().all() = [alloc]
    # n=7: wom_res → scalars().all() = [wom]
    # n=8: wo_res → scalars().all() = [wo]

    def h_items(r): r.scalars.return_value.all.return_value = [inv]
    def h_di(r): r.scalar_one_or_none.return_value = di
    def h_delivery(r): r.scalar_one_or_none.return_value = delivery
    def h_allocs(r): r.scalars.return_value.all.return_value = [alloc]
    def h_woms(r): r.scalars.return_value.all.return_value = [wom]
    def h_wos(r): r.scalars.return_value.all.return_value = [wo]

    session = _make_session(
        user, ["company_admin"], ["inventory.view"],
        [h_items, h_di, h_delivery, h_allocs, h_woms, h_wos],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                f"/api/v1/inventory/trace/{LOT}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()

        assert body["lot_batch_number"] == LOT

        # Source delivery is populated
        src = body["source_delivery"]
        assert src is not None
        assert src["supplier"] == "Acme Metals"
        assert src["bol_reference"] == "BOL-2026-001"
        assert src["delivery_id"] == 1

        # Inventory items present
        assert len(body["inventory_items"]) == 1
        item = body["inventory_items"][0]
        assert item["material_type"] == "Steel Rod"
        assert item["category"] == "raw"

        # Work order that consumed this lot
        assert len(body["work_orders"]) == 1
        wo_info = body["work_orders"][0]
        assert wo_info["work_order_id"] == 1
        assert wo_info["product"] == "Widget A"
        assert wo_info["status"] == "materials_allocated"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Integration Test 2 — Trace lot with no source delivery
# ---------------------------------------------------------------------------

async def test_trace_lot_no_source_delivery():
    """Lot with no source_delivery_item_id → source_delivery is None."""
    user = _make_user()
    token = create_access_token(user_id=1)

    inv = _make_inventory_item(source_delivery_item_id=None)

    # No source delivery IDs → only items + alloc queries
    def h_items(r): r.scalars.return_value.all.return_value = [inv]
    def h_allocs(r): r.scalars.return_value.all.return_value = []

    session = _make_session(
        user, ["company_admin"], ["inventory.view"],
        [h_items, h_allocs],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                f"/api/v1/inventory/trace/{LOT}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["lot_batch_number"] == LOT
        assert body["source_delivery"] is None
        assert len(body["inventory_items"]) == 1
        assert body["work_orders"] == []
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Integration Test 3 — Trace lot that spans multiple inventory items
# ---------------------------------------------------------------------------

async def test_trace_lot_multiple_inventory_items():
    """Same lot split across two inventory items — both appear in traceability view."""
    user = _make_user()
    token = create_access_token(user_id=1)

    inv1 = _make_inventory_item(source_delivery_item_id=None)
    inv2 = _make_inventory_item(source_delivery_item_id=None)
    inv2.id = 101
    inv2.quantity_on_hand = 20.0
    inv2.storage_location = "RACK-B"

    def h_items(r): r.scalars.return_value.all.return_value = [inv1, inv2]
    def h_allocs(r): r.scalars.return_value.all.return_value = []

    session = _make_session(
        user, ["company_admin"], ["inventory.view"],
        [h_items, h_allocs],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                f"/api/v1/inventory/trace/{LOT}",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["inventory_items"]) == 2
        locations = {i["storage_location"] for i in body["inventory_items"]}
        assert "RACK-A" in locations
        assert "RACK-B" in locations
    finally:
        app.dependency_overrides.pop(get_db, None)
