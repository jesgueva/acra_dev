"""
Integration tests — Scenario 1: Full Receiving Workflow.

Flow: login → POST /deliveries → GET /inventory → GET /deliveries with filter.
All tests exercise full HTTP request-response cycles using mocked DB sessions.
"""
from collections import defaultdict
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.delivery import Delivery, DeliveryItem
from app.models.inventory import InventoryItem
from app.models.user import User
from tests.conftest import _make_session, _override

BASE_URL = "http://test"

CLERK_PRIVS = ["deliveries.create", "deliveries.view", "inventory.view"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_user() -> User:
    u = User()
    u.id = 1
    u.username = "clerk1"
    u.full_name = "Receiving Clerk"
    u.preferred_language = "en"
    u.status = "active"
    u.production_line = None
    u.password_hash = hash_password("secret123")
    return u


def _make_login_session(user: User):
    """Mock session for the login endpoint (3 queries: user, roles, privileges + audit write)."""
    session = AsyncMock()
    call_no = {"n": 0}

    async def _execute(query, *args, **kwargs):
        result = MagicMock()
        call_no["n"] += 1
        n = call_no["n"]
        if n == 1:
            result.scalar_one_or_none.return_value = user
        elif n == 2:
            result.fetchall.return_value = [("receiving_clerk",)]
        else:
            result.fetchall.return_value = [(p,) for p in CLERK_PRIVS]
        return result

    session.execute = _execute
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session




def _make_mock_delivery(delivery_id: int = 1) -> Delivery:
    d = Delivery()
    d.id = delivery_id
    d.supplier = "Acme Metals"
    d.carrier = "Fast Freight"
    d.delivery_date = date(2026, 1, 15)
    d.bol_reference = f"BOL-2026-{delivery_id:03d}"
    d.created_by = 1
    d.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
    return d


def _make_mock_delivery_item(item_id: int = 10, delivery_id: int = 1, inv_id: int = 100) -> DeliveryItem:
    di = DeliveryItem()
    di.id = item_id
    di.delivery_id = delivery_id
    di.material_type = "Steel Rod"
    di.quantity = 50.0
    di.lot_batch_number = "LOT-STEEL-001"
    di.storage_location = "RACK-A1"
    di.inventory_item_id = inv_id
    return di


def _make_mock_inventory_item(item_id: int = 100) -> InventoryItem:
    inv = InventoryItem()
    inv.id = item_id
    inv.item_name = "Steel Rod"
    inv.category = "raw"
    inv.quantity_on_hand = 50.0
    inv.lot_batch_number = "LOT-STEEL-001"
    inv.storage_location = "RACK-A1"
    inv.source_delivery_item_id = 10
    inv.last_updated = datetime(2026, 1, 15, tzinfo=timezone.utc)
    return inv


_VALID_DELIVERY_BODY = {
    "supplier": "Acme Metals",
    "carrier": "Fast Freight",
    "delivery_date": "2026-01-15",
    "bol_reference": "BOL-2026-001",
    "items": [
        {
            "material_type": "Steel Rod",
            "quantity": 50.0,
            "lot_batch_number": "LOT-STEEL-001",
            "storage_location": "RACK-A1",
        }
    ],
    "force": False,
}


# ---------------------------------------------------------------------------
# Integration Test 1 — Login succeeds and returns usable token
# ---------------------------------------------------------------------------

async def test_login_returns_token_for_clerk():
    """Step 1 of workflow: Clerk logs in and receives a bearer token."""
    user = _make_user()
    session = _make_login_session(user)
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"username": "clerk1", "password": "secret123"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["user"]["full_name"] == "Receiving Clerk"
        assert "deliveries.create" in body["user"]["effective_privileges"]
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Integration Test 2 — POST /deliveries creates delivery and inventory items
# ---------------------------------------------------------------------------

async def test_create_delivery_creates_inventory_items():
    """Step 2: POST /deliveries returns 201 and links inventory_item_id."""
    user = _make_user()
    token = create_access_token(user_id=1)

    added = defaultdict(list)

    def h_bol_check(r):
        r.scalar_one_or_none.return_value = None  # no duplicate

    session = _make_session(user, ["receiving_clerk"], CLERK_PRIVS, [h_bol_check])

    # Wire flush to assign IDs
    async def _flush():
        for d in added.get("deliveries", []):
            if d.id is None:
                d.id = 1
                d.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
        for idx, item in enumerate(added.get("delivery_items", [])):
            if item.id is None:
                item.id = 10 + idx
        for idx, inv in enumerate(added.get("inventory_items", [])):
            if inv.id is None:
                inv.id = 100 + idx

    session.add = MagicMock(side_effect=lambda obj: added[obj.__class__.__tablename__].append(obj))
    session.flush = _flush

    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/deliveries",
                json=_VALID_DELIVERY_BODY,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["bol_reference"] == "BOL-2026-001"
        assert body["supplier"] == "Acme Metals"
        assert len(body["items"]) == 1
        # inventory_item_id is linked back
        assert body["items"][0]["inventory_item_id"] == 100
        assert body["items"][0]["lot_batch_number"] == "LOT-STEEL-001"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Integration Test 3 — GET /inventory reflects the newly received items
# ---------------------------------------------------------------------------

async def test_inventory_shows_received_items():
    """Step 3: GET /inventory returns items with correct fields after a delivery."""
    user = _make_user()
    token = create_access_token(user_id=1)
    inv = _make_mock_inventory_item()

    def h_count(r): r.scalar.return_value = 1
    def h_items(r): r.scalars.return_value.all.return_value = [inv]
    def h_alerts(r): r.scalars.return_value.all.return_value = []

    session = _make_session(user, ["receiving_clerk"], CLERK_PRIVS, [h_count, h_items, h_alerts])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/inventory",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        item = body["results"][0]
        assert item["material_type"] == "Steel Rod"
        assert item["category"] == "raw"
        assert item["quantity_on_hand"] == 50.0
        assert item["lot_batch_number"] == "LOT-STEEL-001"
        assert item["source_delivery_item_id"] == 10
        assert item["is_triggered"] is False
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Integration Test 4 — GET /deliveries with supplier filter
# ---------------------------------------------------------------------------

async def test_list_deliveries_with_supplier_filter():
    """Step 4: GET /deliveries?supplier=Acme returns only matching deliveries."""
    user = _make_user()
    token = create_access_token(user_id=1)
    delivery = _make_mock_delivery()
    item = _make_mock_delivery_item()

    def h_count(r): r.scalar.return_value = 1
    def h_deliveries(r): r.scalars.return_value.all.return_value = [delivery]
    def h_items(r): r.scalars.return_value.all.return_value = [item]

    session = _make_session(user, ["receiving_clerk"], CLERK_PRIVS, [h_count, h_deliveries, h_items])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/deliveries",
                params={"supplier": "Acme Metals", "page": 1, "page_size": 20},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["page"] == 1
        result = body["results"][0]
        assert result["supplier"] == "Acme Metals"
        assert result["bol_reference"] == "BOL-2026-001"
        assert len(result["items"]) == 1
        assert result["items"][0]["lot_batch_number"] == "LOT-STEEL-001"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Integration Test 5 — Duplicate BOL is rejected (409) unless force=True
# ---------------------------------------------------------------------------

async def test_duplicate_bol_rejected_then_forced():
    """Workflow: first attempt with duplicate BOL → 409; second with force=True → 201."""
    user = _make_user()
    token = create_access_token(user_id=1)
    existing_delivery = _make_mock_delivery()

    # Attempt 1: duplicate BOL → 409
    def h_bol_exists(r):
        r.scalar_one_or_none.return_value = existing_delivery

    session1 = _make_session(user, ["receiving_clerk"], CLERK_PRIVS, [h_bol_exists])
    app.dependency_overrides[get_db] = _override(session1)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/deliveries",
                json=_VALID_DELIVERY_BODY,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 409
        assert "BOL-2026-001" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)

    # Attempt 2: force=True → 201 despite duplicate
    added = defaultdict(list)

    def h_bol_exists_again(r):
        r.scalar_one_or_none.return_value = existing_delivery

    session2 = _make_session(user, ["receiving_clerk"], CLERK_PRIVS, [h_bol_exists_again])

    async def _flush():
        for d in added.get("deliveries", []):
            if d.id is None:
                d.id = 2
                d.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
        for idx, i in enumerate(added.get("delivery_items", [])):
            if i.id is None:
                i.id = 20 + idx
        for idx, inv in enumerate(added.get("inventory_items", [])):
            if inv.id is None:
                inv.id = 200 + idx

    session2.add = MagicMock(side_effect=lambda obj: added[obj.__class__.__tablename__].append(obj))
    session2.flush = _flush

    app.dependency_overrides[get_db] = _override(session2)
    try:
        forced_body = {**_VALID_DELIVERY_BODY, "force": True}
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/deliveries",
                json=forced_body,
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 201
        assert resp.json()["bol_reference"] == "BOL-2026-001"
    finally:
        app.dependency_overrides.pop(get_db, None)
