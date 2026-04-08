"""
Schema tests for T02 — verifies all 11 tables, seed data, constraints, and indices
exist after running `alembic upgrade head`.

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


async def test_all_11_tables_exist(conn):
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
        "deliveries",
        "delivery_items",
        "inventory_items",
        "work_orders",
        "work_order_materials",
        "material_allocations",
        "audit_logs",
        "low_stock_alerts",
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


async def test_inventory_items_category_check_constraint(conn):
    """category must be 'raw' or 'finished'."""
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            """
            INSERT INTO inventory_items
                (material_type, category, quantity_on_hand, lot_batch_number, storage_location)
            VALUES ('TestMat', 'bad_category', 0, 'LOT-001', 'A-01')
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
