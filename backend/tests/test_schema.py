"""
Schema tests — verifies core tables, seed data, constraints, and indices exist
after running `alembic upgrade head`.

Requires a running PostgreSQL database with acra_db created and migrations applied.
"""
import os

import asyncpg
import pytest

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db",
)
PG_DSN = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def conn():
    connection = await asyncpg.connect(PG_DSN)
    yield connection
    await connection.close()


async def test_core_tables_exist(conn):
    rows = await conn.fetch(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        """
    )
    table_names = {r["table_name"] for r in rows}
    expected = {
        "users",
        "roles",
        "user_role_assignments",
        "role_privilege_assignments",
        "contacts",
        "products",
        "deliveries",
        "delivery_items",
        "inventory_lots",
        "inventory_transactions",
        "work_orders",
        "work_order_materials",
        "material_allocations",
        "audit_logs",
        "low_stock_alerts",
        "shipments",
        "shipment_items",
        "production_worksheets",
        "production_worksheet_lines",
    }
    assert expected.issubset(table_names), (
        f"Missing tables: {expected - table_names}"
    )


async def test_roles_seed_data(conn):
    rows = await conn.fetch("SELECT role_name FROM roles ORDER BY role_name")
    role_names = {r["role_name"] for r in rows}
    assert role_names == {
        "company_admin",
        "machine_operator",
        "production_supervisor",
        "receiving_clerk",
    }


async def test_users_status_check_constraint(conn):
    """Invalid status value must be rejected by the database."""
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            """
            INSERT INTO users (username, password_hash, full_name, status)
            VALUES ('__test__', 'hash', 'Test User', 'invalid_status')
            """
        )


async def test_inventory_lots_status_check_constraint(conn):
    """status must be one of the allowed inventory_lots values."""
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            """
            INSERT INTO inventory_lots
                (lot_number, storage_location, status, quantity_on_hand)
            VALUES ('LOT-001', 'A-01', 'bad_status', 0)
            """
        )


async def test_audit_log_indices_exist(conn):
    rows = await conn.fetch(
        """
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = 'audit_logs' AND schemaname = 'public'
        """
    )
    index_names = {r["indexname"] for r in rows}
    assert "idx_audit_logs_entity" in index_names
    assert "idx_audit_logs_user" in index_names
    assert "idx_audit_logs_time" in index_names
