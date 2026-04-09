"""
Tests for T09 — Inventory API.
Expected: 11 passed, 0 failed.
All tests run without a live database connection.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.inventory import InventoryItem, LowStockAlert
from app.models.user import User

BASE_URL = "http://test"
PRIVS_VIEW = ["inventory.view"]
PRIVS_ADJUST = ["inventory.view", "inventory.adjust"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user() -> User:
    u = User()
    u.id = 1
    u.username = "admin"
    u.full_name = "Admin User"
    u.preferred_language = "en"
    u.status = "active"
    u.password_hash = hash_password("password123")
    return u


def _make_item(
    id: int = 1,
    material_type: str = "Steel",
    category: str = "raw",
    quantity_on_hand: float = 100.0,
    lot_batch_number: str = "LOT-001",
    storage_location: str = "A1",
    source_delivery_item_id=None,
) -> InventoryItem:
    item = InventoryItem()
    item.id = id
    item.material_type = material_type
    item.category = category
    item.quantity_on_hand = quantity_on_hand
    item.lot_batch_number = lot_batch_number
    item.storage_location = storage_location
    item.source_delivery_item_id = source_delivery_item_id
    item.last_updated = datetime.now(timezone.utc)
    return item


def _make_alert(
    id: int = 1,
    material_type: str = "Steel",
    threshold: float = 50.0,
) -> LowStockAlert:
    a = LowStockAlert()
    a.id = id
    a.material_type = material_type
    a.threshold = threshold
    a.created_by = 1
    return a


def _make_session(user, roles, privileges, service_handlers=None):
    """
    Build a mock AsyncSession.

    - Execute calls 0-2: RBAC (user lookup, roles, privileges)
    - Execute calls 3+: service_handlers[i](result_mock) for sequential service queries
    """
    service_handlers = service_handlers or []
    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        n = call_no["n"]
        call_no["n"] += 1
        if n == 0:
            result.scalar_one_or_none.return_value = user
        elif n == 1:
            result.fetchall.return_value = [(r,) for r in roles]
        elif n == 2:
            result.fetchall.return_value = [(p,) for p in privileges]
        else:
            svc_idx = n - 3
            if svc_idx < len(service_handlers):
                service_handlers[svc_idx](result)
        return result

    session.execute = _execute
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    return session


def _override(session):
    async def _dep():
        yield session
    return _dep


# ---------------------------------------------------------------------------
# Test 1 — GET /inventory returns 200 with paginated results
# ---------------------------------------------------------------------------
async def test_list_inventory_returns_200():
    user = _make_user()
    item = _make_item()

    def h_count(r): r.scalar.return_value = 1
    def h_items(r): r.scalars.return_value.all.return_value = [item]
    def h_alerts(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["admin"], PRIVS_VIEW, [h_count, h_items, h_alerts])
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
        assert body["results"][0]["material_type"] == "Steel"
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
# Test 3 — PATCH /{id} adjusts quantity and returns 200
# ---------------------------------------------------------------------------
async def test_adjust_quantity_success():
    user = _make_user()
    item = _make_item(quantity_on_hand=100.0)

    def h_item(r): r.scalar_one_or_none.return_value = item

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_item])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/inventory/1",
                headers={"Authorization": f"Bearer {token}"},
                json={"quantity_on_hand": 75.0, "reason": "Manual correction"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 1
        assert body["quantity_on_hand"] == 75.0
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 4 — PATCH /{id} with unknown id returns 404
# ---------------------------------------------------------------------------
async def test_adjust_quantity_not_found():
    user = _make_user()

    def h_item(r): r.scalar_one_or_none.return_value = None

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_item])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/inventory/999",
                headers={"Authorization": f"Bearer {token}"},
                json={"quantity_on_hand": 50.0, "reason": "Test"},
            )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 5 — GET /trace/{lot} returns traceability data
# ---------------------------------------------------------------------------
async def test_trace_lot_returns_200():
    user = _make_user()
    item = _make_item(lot_batch_number="LOT-001", source_delivery_item_id=None)

    def h_items(r): r.scalars.return_value.all.return_value = [item]
    def h_allocs(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["admin"], PRIVS_VIEW, [h_items, h_allocs])
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
        assert body["lot_batch_number"] == "LOT-001"
        assert len(body["inventory_items"]) == 1
        assert body["work_orders"] == []
        assert body["source_delivery"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 6 — GET /alerts returns alerts with computed is_triggered
# ---------------------------------------------------------------------------
async def test_list_alerts_returns_200():
    user = _make_user()
    alert = _make_alert(material_type="Steel", threshold=50.0)

    def h_alerts(r): r.scalars.return_value.all.return_value = [alert]
    def h_qty(r): r.all.return_value = [("Steel", 30.0)]  # 30 <= 50 → triggered

    session = _make_session(user, ["admin"], PRIVS_VIEW, [h_alerts, h_qty])
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
        assert a["material_type"] == "Steel"
        assert a["current_quantity"] == 30.0
        assert a["is_triggered"] is True
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 7 — POST /alerts creates a new alert (returns 201)
# ---------------------------------------------------------------------------
async def test_create_alert_success():
    user = _make_user()

    def h_existing(r): r.scalar_one_or_none.return_value = None  # no existing

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_existing])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/inventory/alerts",
                headers={"Authorization": f"Bearer {token}"},
                json={"material_type": "Copper", "threshold": 25.0},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["material_type"] == "Copper"
        assert body["threshold"] == 25.0
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 8 — POST /alerts upserts existing alert (returns 201 with new threshold)
# ---------------------------------------------------------------------------
async def test_create_alert_upsert():
    user = _make_user()
    existing = _make_alert(id=1, material_type="Steel", threshold=50.0)

    def h_existing(r): r.scalar_one_or_none.return_value = existing

    session = _make_session(user, ["admin"], PRIVS_ADJUST, [h_existing])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/inventory/alerts",
                headers={"Authorization": f"Bearer {token}"},
                json={"material_type": "Steel", "threshold": 100.0},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["material_type"] == "Steel"
        assert body["threshold"] == 100.0
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Test 9 — DELETE /alerts/{id} returns 204
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
# Test 10 — DELETE /alerts/{id} for missing alert returns 404
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


# ---------------------------------------------------------------------------
# Test 11 — GET /export returns text/csv with inventory rows
# ---------------------------------------------------------------------------
async def test_export_csv_returns_csv():
    user = _make_user()
    item = _make_item()

    def h_items(r): r.scalars.return_value.all.return_value = [item]
    def h_alerts(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["admin"], PRIVS_VIEW, [h_items, h_alerts])
    app.dependency_overrides[get_db] = _override(session)
    try:
        token = create_access_token(user_id=1)
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/inventory/export",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "Steel" in resp.text
        assert "material_type" in resp.text  # header row present
    finally:
        app.dependency_overrides.pop(get_db, None)
