"""
Integration tests — Scenario 5: RBAC Boundary Tests.

Covers:
- Machine Operator sees only work orders for their production line
- Clerk gets 403 on work order endpoints (missing privilege)
- Expired JWT returns 401
- Missing privilege returns 403 on protected endpoints
"""
from datetime import date, datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.user import User
from app.models.work_order import WorkOrder, WorkOrderMaterial
from tests.conftest import _make_session, _override

BASE_URL = "http://test"


def _make_user(production_line: str | None = None, username: str = "testuser") -> User:
    u = User()
    u.id = 1
    u.username = username
    u.full_name = "Test User"
    u.preferred_language = "en"
    u.status = "active"
    u.production_line = production_line
    u.password_hash = hash_password("pw123")
    return u


def _make_wo(id: int = 1, production_line: str = "Line A") -> WorkOrder:
    wo = WorkOrder()
    wo.id = id
    wo.product = "Widget A"
    wo.status = "created"
    wo.priority = "medium"
    wo.display_sequence = 0
    wo.production_line = production_line
    wo.quantity_required = 10.0
    wo.quantity_produced = 0.0
    wo.target_date = date(2026, 5, 1)
    wo.created_by = 1
    wo.created_at = datetime.now(timezone.utc)
    wo.updated_at = datetime.now(timezone.utc)
    return wo


def _make_material() -> WorkOrderMaterial:
    m = WorkOrderMaterial()
    m.id = 1
    m.work_order_id = 1
    m.material_type = "Steel"
    m.quantity_required = 5.0
    m.quantity_allocated = 0.0
    return m


# ---------------------------------------------------------------------------
# RBAC Test 1 — Machine Operator sees only their production line WOs
# ---------------------------------------------------------------------------

async def test_machine_operator_line_filter():
    """Machine Operator on Line A only sees WOs assigned to Line A."""
    user = _make_user(production_line="Line A")
    token = create_access_token(user_id=1)
    wo = _make_wo(production_line="Line A")
    mat = _make_material()

    def h_count(r): r.scalar.return_value = 1
    def h_wos(r): r.scalars.return_value.all.return_value = [wo]
    def h_mats(r): r.scalars.return_value.all.return_value = [mat]

    session = _make_session(
        user, ["machine_operator"], ["work_orders.view"],
        [h_count, h_wos, h_mats],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
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


async def test_machine_operator_denied_wo_on_different_line():
    """Machine Operator on Line A gets 403 when accessing a WO on Line B."""
    user = _make_user(production_line="Line A")
    token = create_access_token(user_id=1)
    wo = _make_wo(production_line="Line B")

    def h_wo(r): r.scalar_one_or_none.return_value = wo

    session = _make_session(
        user, ["machine_operator"], ["work_orders.view"],
        [h_wo],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/work-orders/1",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# RBAC Test 2 — Clerk 403 on work order endpoints
# ---------------------------------------------------------------------------

async def test_clerk_cannot_list_work_orders():
    """Receiving Clerk without work_orders.view privilege gets 403 on GET /work-orders."""
    user = _make_user()
    token = create_access_token(user_id=1)

    session = _make_session(
        user, ["receiving_clerk"], ["deliveries.create", "deliveries.view"],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/work-orders",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_clerk_cannot_create_work_order():
    """Receiving Clerk without work_orders.create privilege gets 403 on POST /work-orders."""
    user = _make_user()
    token = create_access_token(user_id=1)

    session = _make_session(
        user, ["receiving_clerk"], ["deliveries.create", "deliveries.view"],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/work-orders",
                json={
                    "product": "Widget B",
                    "quantity_required": 5.0,
                    "priority": "low",
                    "target_date": "2026-06-01",
                    "materials": [{"material_type": "Rubber", "quantity_required": 2.0}],
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# RBAC Test 3 — Expired JWT returns 401
# ---------------------------------------------------------------------------

async def test_expired_jwt_returns_401():
    """Request with an expired JWT token is rejected with 401."""
    expired_token = create_access_token(
        user_id=1,
        expires_delta=timedelta(seconds=-1),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        resp = await client.get(
            "/api/v1/work-orders",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# RBAC Test 4 — Missing privilege returns 403
# ---------------------------------------------------------------------------

async def test_missing_audit_privilege_returns_403():
    """User without audit.view cannot access GET /audit-logs."""
    user = _make_user()
    token = create_access_token(user_id=1)

    session = _make_session(
        user, ["receiving_clerk"], ["deliveries.create", "deliveries.view"],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/audit-logs",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_missing_inventory_adjust_privilege_returns_403():
    """User with only inventory.view cannot PATCH /inventory/{id}."""
    user = _make_user()
    token = create_access_token(user_id=1)

    session = _make_session(
        user, ["receiving_clerk"], ["inventory.view"],
    )
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.patch(
                "/api/v1/inventory/1",
                json={"quantity_on_hand": 50.0, "reason": "test"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# RBAC Test 5 — No token returns 401/403
# ---------------------------------------------------------------------------

async def test_no_token_on_protected_endpoint():
    """Requests without Authorization header are rejected."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
        for path in [
            "/api/v1/work-orders",
            "/api/v1/inventory",
            "/api/v1/deliveries",
            "/api/v1/audit-logs",
        ]:
            resp = await client.get(path)
            assert resp.status_code in (401, 403), f"Expected 401/403 for {path}, got {resp.status_code}"
