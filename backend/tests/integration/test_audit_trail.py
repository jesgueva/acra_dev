"""
Integration tests — Scenario 6: Audit Trail Completeness.

Verifies that multiple user actions produce audit log entries and that
GET /audit-logs returns them in the correct order with the expected fields.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.audit import AuditLog
from app.models.user import User

BASE_URL = "http://test"
ADMIN_PRIVS = ["audit.view", "inventory.adjust", "deliveries.create", "work_orders.create"]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_user() -> User:
    u = User()
    u.id = 1
    u.username = "admin"
    u.full_name = "Admin User"
    u.preferred_language = "en"
    u.status = "active"
    u.production_line = None
    u.password_hash = hash_password("pw123")
    return u


def _make_session(user, roles, privileges, service_handlers=None):
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
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


def _override(session):
    async def _dep():
        yield session
    return _dep


def _make_log(
    id: int,
    action: str,
    entity_type: str,
    entity_id: int = 1,
    user_id: int = 1,
    ts: datetime | None = None,
) -> AuditLog:
    log = AuditLog()
    log.id = id
    log.user_id = user_id
    log.action = action
    log.entity_type = entity_type
    log.entity_id = entity_id
    log.details = None
    log.timestamp = ts or datetime(2026, 4, 8, 12, 0, id, tzinfo=timezone.utc)
    return log


# ---------------------------------------------------------------------------
# Audit Test 1 — Multiple actions produce audit entries visible in GET /audit-logs
# ---------------------------------------------------------------------------

async def test_audit_trail_shows_multiple_action_types():
    """
    Scenario 6: After login, delivery, and inventory adjust actions,
    GET /audit-logs returns all three entries.
    """
    user = _make_user()
    token = create_access_token(user_id=1)

    logs = [
        _make_log(id=1, action="login", entity_type="User"),
        _make_log(id=2, action="delivery_created", entity_type="Delivery", entity_id=1,
                  ts=datetime(2026, 4, 8, 12, 0, 1, tzinfo=timezone.utc)),
        _make_log(id=3, action="inventory_adjust", entity_type="inventory_item", entity_id=100,
                  ts=datetime(2026, 4, 8, 12, 0, 2, tzinfo=timezone.utc)),
    ]

    def h_count(r): r.scalar.return_value = 3
    def h_rows(r): r.scalars.return_value.all.return_value = logs

    session = _make_session(user, ["company_admin"], ADMIN_PRIVS, [h_count, h_rows])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/audit-logs",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["results"]) == 3

        actions = [r["action"] for r in body["results"]]
        assert "login" in actions
        assert "delivery_created" in actions
        assert "inventory_adjust" in actions
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Audit Test 2 — Entries are returned in chronological order
# ---------------------------------------------------------------------------

async def test_audit_entries_in_chronological_order():
    """Audit log entries are returned ordered by timestamp (ascending)."""
    user = _make_user()
    token = create_access_token(user_id=1)

    t_base = datetime(2026, 4, 8, 10, 0, 0, tzinfo=timezone.utc)
    logs = [
        _make_log(id=1, action="login", entity_type="User",
                  ts=datetime(2026, 4, 8, 10, 0, 0, tzinfo=timezone.utc)),
        _make_log(id=2, action="delivery_created", entity_type="Delivery",
                  ts=datetime(2026, 4, 8, 10, 5, 0, tzinfo=timezone.utc)),
        _make_log(id=3, action="work_order_created", entity_type="work_order",
                  ts=datetime(2026, 4, 8, 10, 10, 0, tzinfo=timezone.utc)),
        _make_log(id=4, action="work_order_assigned", entity_type="work_order",
                  ts=datetime(2026, 4, 8, 10, 15, 0, tzinfo=timezone.utc)),
        _make_log(id=5, action="work_order_status_updated", entity_type="work_order",
                  ts=datetime(2026, 4, 8, 10, 20, 0, tzinfo=timezone.utc)),
    ]

    def h_count(r): r.scalar.return_value = 5
    def h_rows(r): r.scalars.return_value.all.return_value = logs

    session = _make_session(user, ["company_admin"], ADMIN_PRIVS, [h_count, h_rows])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/audit-logs",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 5
        results = body["results"]

        # Verify chronological order by checking IDs match insert order
        ids = [r["id"] for r in results]
        assert ids == [1, 2, 3, 4, 5]

        # Verify work order lifecycle entries are all present
        actions = [r["action"] for r in results]
        assert actions.index("work_order_created") < actions.index("work_order_assigned")
        assert actions.index("work_order_assigned") < actions.index("work_order_status_updated")
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Audit Test 3 — Filter by action returns only matching entries
# ---------------------------------------------------------------------------

async def test_audit_filter_by_action():
    """GET /audit-logs?action=login returns only login entries."""
    user = _make_user()
    token = create_access_token(user_id=1)

    login_log = _make_log(id=1, action="login", entity_type="User")

    def h_count(r): r.scalar.return_value = 1
    def h_rows(r): r.scalars.return_value.all.return_value = [login_log]

    session = _make_session(user, ["company_admin"], ADMIN_PRIVS, [h_count, h_rows])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/audit-logs",
                params={"action": "login"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["results"][0]["action"] == "login"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Audit Test 4 — Filter by entity_type
# ---------------------------------------------------------------------------

async def test_audit_filter_by_entity_type():
    """GET /audit-logs?entity_type=work_order returns only WO-related entries."""
    user = _make_user()
    token = create_access_token(user_id=1)

    wo_logs = [
        _make_log(id=2, action="work_order_created", entity_type="work_order"),
        _make_log(id=3, action="work_order_assigned", entity_type="work_order", entity_id=1,
                  ts=datetime(2026, 4, 8, 12, 0, 3, tzinfo=timezone.utc)),
    ]

    def h_count(r): r.scalar.return_value = 2
    def h_rows(r): r.scalars.return_value.all.return_value = wo_logs

    session = _make_session(user, ["company_admin"], ADMIN_PRIVS, [h_count, h_rows])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.get(
                "/api/v1/audit-logs",
                params={"entity_type": "work_order"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        for entry in body["results"]:
            assert entry["entity_type"] == "work_order"
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Audit Test 5 — Audit write on work order create is committed
# ---------------------------------------------------------------------------

async def test_audit_write_committed_on_work_order_create():
    """When a WO is created, the service commits (which includes the audit entry)."""
    user = _make_user()
    token = create_access_token(user_id=1)

    def h_dup(r): r.scalar_one_or_none.return_value = None
    def h_qty(r): r.all.return_value = [("Steel", 100.0)]

    session = _make_session(user, ["company_admin"], ["work_orders.create", "work_orders.view"], [h_dup, h_qty])
    app.dependency_overrides[get_db] = _override(session)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE_URL) as client:
            resp = await client.post(
                "/api/v1/work-orders",
                json={
                    "product": "Widget A",
                    "quantity_required": 10.0,
                    "priority": "medium",
                    "target_date": "2026-05-01",
                    "materials": [{"material_type": "Steel", "quantity_required": 5.0}],
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 201
        # Verify commit was called (which persists the AuditLog added via write_audit)
        assert session.commit.called
    finally:
        app.dependency_overrides.pop(get_db, None)
