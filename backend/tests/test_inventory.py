"""
Tests for Phase-3 Inventory API (ledger model).
Expected: 14 passed, 0 failed.
All tests run without a live database connection.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.inventory import InventoryLot, InventoryTransaction, LowStockAlert
from app.models.user import User
from tests.conftest import _make_session, _make_user, _override

BASE_URL = "http://test"
PRIVS_VIEW = ["inventory.view"]
PRIVS_ADJUST = ["inventory.view", "inventory.adjust"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lot(
    id: int = 1,
    product_id: int | None = 1,
    lot_number: str | None = "LOT-001",
    storage_location: str | None = "A1",
    status: str = "in_storage",
    quantity_on_hand: int = 10000,  # 100.00 units ×100
    source_delivery_item_id: int | None = None,
) -> InventoryLot:
    lot = InventoryLot()
    lot.id = id
    lot.product_id = product_id
    lot.lot_number = lot_number
    lot.storage_location = storage_location
    lot.status = status
    lot.quantity_on_hand = quantity_on_hand
    lot.source_delivery_item_id = source_delivery_item_id
    lot.pallet_number = None
    return lot


def _make_txn(
    id: int = 1,
    lot_id: int = 1,
    transaction_type: str = "receive",
    quantity: int = 10000,
) -> InventoryTransaction:
    txn = InventoryTransaction()
    txn.id = id
    txn.lot_id = lot_id
    txn.transaction_type = transaction_type
    txn.quantity = quantity
    txn.reference_type = None
    txn.reference_id = None
    txn.reason = "Test"
    txn.created_by = 1
    txn.created_at = datetime.now(timezone.utc)
    return txn


def _make_alert(
    id: int = 1,
    product_id: int | None = 1,
    threshold: int = 5000,  # 50.00 units ×100
) -> LowStockAlert:
    a = LowStockAlert()
    a.id = id
    a.product_id = product_id
    a.threshold = threshold
    a.created_by = 1
    return a


# ---------------------------------------------------------------------------
# Test 1 — GET /inventory returns 200 with paginated lots
# ---------------------------------------------------------------------------
async def test_list_inventory_returns_200():
    user = _make_user()
    lot = _make_lot()

    def h_count(r): r.scalar.return_value = 1
    def h_lots(r): r.scalars.return_value.all.return_value = [lot]
    def h_alerts(r): r.scalars.return_value.all.return_value = []
    def h_products(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["admin"], PRIVS_VIEW, [h_count, h_lots, h_alerts, h_products])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/inventory",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["results"]) == 1
        r = body["results"][0]
        assert r["status"] == "in_storage"
        assert r["quantity_on_hand"] == 10000
        assert r["lot_number"] == "LOT-001"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 2 — No auth returns 401/403
# ---------------------------------------------------------------------------
async def test_list_inventory_no_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get("/api/v1/inventory")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Test 3 — PATCH /{id} creates an adjust transaction and returns 200
# ---------------------------------------------------------------------------
async def test_adjust_quantity_creates_transaction():
    user = _make_user()
    lot = _make_lot(quantity_on_hand=10000)

    def h_lot(r): r.scalar_one_or_none.return_value = lot

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_lot])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/inventory/1",
                headers={"Authorization": f"Bearer {token}"},
                json={"delta": -500, "reason": "Damage adjustment"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 1
        assert body["quantity_on_hand"] == 9500
        # InventoryTransaction was added via session.add
        assert session.add.called
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 4 — PATCH /{id} with unknown id returns 404
# ---------------------------------------------------------------------------
async def test_adjust_quantity_not_found():
    user = _make_user()

    def h_lot(r): r.scalar_one_or_none.return_value = None

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_lot])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/inventory/999",
                headers={"Authorization": f"Bearer {token}"},
                json={"delta": -100, "reason": "Test"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 5 — PATCH /{id} that would go negative returns 422
# ---------------------------------------------------------------------------
async def test_adjust_quantity_negative_rejected():
    user = _make_user()
    lot = _make_lot(quantity_on_hand=100)

    def h_lot(r): r.scalar_one_or_none.return_value = lot

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_lot])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/inventory/1",
                headers={"Authorization": f"Bearer {token}"},
                json={"delta": -500, "reason": "Too large deduction"},
            )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 6 — PATCH /lots/{id}/location returns updated lot
# ---------------------------------------------------------------------------
async def test_update_location_success():
    user = _make_user()
    lot = _make_lot(storage_location="A1")

    def h_lot(r): r.scalar_one_or_none.return_value = lot
    def h_products(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_lot, h_products])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/inventory/lots/1/location",
                headers={"Authorization": f"Bearer {token}"},
                json={"storage_location": "B5"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["storage_location"] == "B5"
        assert session.add.called  # move transaction added
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 7 — PATCH /lots/{id}/location with unknown lot returns 404
# ---------------------------------------------------------------------------
async def test_update_location_not_found():
    user = _make_user()

    def h_lot(r): r.scalar_one_or_none.return_value = None

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_lot])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/inventory/lots/999/location",
                headers={"Authorization": f"Bearer {token}"},
                json={"storage_location": "C1"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 8 — POST /lots/{id}/split creates a sibling lot (201)
# ---------------------------------------------------------------------------
async def test_split_lot_success():
    user = _make_user()
    lot = _make_lot(quantity_on_hand=10000)
    new_id_counter = {"n": 2}

    def h_lot(r): r.scalar_one_or_none.return_value = lot

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_lot])

    # Override add to auto-assign id to any new InventoryLot without one
    original_add = session.add
    def patched_add(obj):
        if isinstance(obj, InventoryLot) and obj.id is None:
            obj.id = new_id_counter["n"]
            new_id_counter["n"] += 1
        original_add(obj)
    session.add = patched_add

    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/inventory/lots/1/split",
                headers={"Authorization": f"Bearer {token}"},
                json={"split_quantity": 3000, "storage_location": "B3"},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["source_lot"]["quantity_on_hand"] == 7000
        assert body["new_lot_quantity"] == 3000
        assert isinstance(body["new_lot_id"], int)
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 9 — POST /lots/{id}/split with qty > lot qty returns 422
# ---------------------------------------------------------------------------
async def test_split_lot_insufficient_quantity():
    user = _make_user()
    lot = _make_lot(quantity_on_hand=1000)

    def h_lot(r): r.scalar_one_or_none.return_value = lot

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_lot])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/inventory/lots/1/split",
                headers={"Authorization": f"Bearer {token}"},
                json={"split_quantity": 9999, "storage_location": "B3"},
            )
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 10 — GET /trace/{lot_number} returns traceability data
# ---------------------------------------------------------------------------
async def test_trace_lot_returns_200():
    user = _make_user()
    lot = _make_lot(lot_number="LOT-001", source_delivery_item_id=None)

    def h_lots(r): r.scalars.return_value.all.return_value = [lot]
    def h_products(r): r.scalars.return_value.all.return_value = []
    def h_allocs(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["admin"], PRIVS_VIEW, [h_lots, h_products, h_allocs])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/inventory/trace/LOT-001",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["lot_number"] == "LOT-001"
        assert len(body["lots"]) == 1
        assert body["lots"][0]["quantity_on_hand"] == 10000
        assert body["work_orders"] == []
        assert body["source_delivery"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 11 — GET /alerts returns alerts with is_triggered based on integer qty
# ---------------------------------------------------------------------------
async def test_list_alerts_returns_200():
    user = _make_user()
    alert = _make_alert(product_id=1, threshold=5000)  # 50.00 units

    def h_alerts(r): r.scalars.return_value.all.return_value = [alert]
    def h_products(r): r.scalars.return_value.all.return_value = []
    def h_qty(r): r.all.return_value = [(1, 3000)]  # 30.00 ≤ 50.00 → triggered

    session = _make_session(user, ["admin"], PRIVS_VIEW, [h_alerts, h_products, h_qty])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/inventory/alerts",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["alerts"]) == 1
        a = body["alerts"][0]
        assert a["product_id"] == 1
        assert a["threshold"] == 5000
        assert a["current_quantity"] == 3000
        assert a["is_triggered"] is True
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 12 — POST /alerts creates a new alert (returns 201)
# ---------------------------------------------------------------------------
async def test_create_alert_success():
    user = _make_user()

    added = []
    def h_existing(r): r.scalar_one_or_none.return_value = None
    def h_products(r): r.scalars.return_value.all.return_value = []
    def h_stock(r): r.scalar.return_value = 0

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_existing, h_products, h_stock])

    original_add = session.add
    session.add = lambda obj: [original_add(obj), added.append(obj)]

    async def fake_flush():
        for obj in added:
            if hasattr(obj, "id") and obj.id is None:
                obj.id = 99
    session.flush = fake_flush

    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/inventory/alerts",
                headers={"Authorization": f"Bearer {token}"},
                json={"product_id": 2, "threshold": 2500},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["product_id"] == 2
        assert body["threshold"] == 2500
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 13 — DELETE /alerts/{id} returns 204
# ---------------------------------------------------------------------------
async def test_delete_alert_success():
    user = _make_user()
    alert = _make_alert()

    def h_alert(r): r.scalar_one_or_none.return_value = alert

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_alert])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.delete(
                "/api/v1/inventory/alerts/1",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 204
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 14 — DELETE /alerts/{id} for missing alert returns 404
# ---------------------------------------------------------------------------
async def test_delete_alert_not_found():
    user = _make_user()

    def h_alert(r): r.scalar_one_or_none.return_value = None

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_alert])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.delete(
                "/api/v1/inventory/alerts/999",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)
