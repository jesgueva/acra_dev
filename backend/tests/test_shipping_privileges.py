"""
ACR-35 — the role-privilege seed must cover every privilege the routers enforce.

`require_privilege` resolves names at request time straight from `role_privilege_assignments`
(`app/core/rbac.py`), so a privilege that no migration grants is not a config gap — it is a
permanent 403 for every user, including `company_admin`. That is exactly how `shipping.view` and
`shipping.create` shipped: enforced by `routers/shipments.py`, granted by nobody.

These tests read the privileges out of the router source and compare them against what a database
built from `alembic upgrade head` actually grants, so the next unseeded privilege fails here rather
than in production.

Requires a running PostgreSQL database with migrations applied (same as `test_schema.py`).
"""
import ast
import os
from pathlib import Path

import asyncpg
import pytest

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db",
)
PG_DSN = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

ROUTERS_DIR = Path(__file__).resolve().parent.parent / "app" / "routers"

# `require_privilege("authenticated")` is the documented escape hatch for "any valid JWT" — it is
# deliberately not a row in the table (see `app/core/rbac.py`).
_SENTINEL_PRIVILEGES = {"authenticated"}

# Privileges enforced by a router that no migration grants. Same defect as ACR-35, different
# privilege: `master_data.*` is required by routers/contacts.py and routers/products.py but seeded
# only by scripts/seed_fake_data.py, so contacts and products 403 on a migrations-only database.
# Tracked separately — deliberately out of ACR-35's scope rather than silently widened into it.
_UNSEEDED_KNOWN_GAPS = {"master_data.view", "master_data.manage"}

# The mapping migration 011 seeds. Mirrors the deliveries.create / deliveries.view split: the clerk
# works the dock in both directions, the supervisor sees outbound stock leave but does not book it.
EXPECTED_SHIPPING_GRANTS = {
    ("shipping.view", "company_admin"),
    ("shipping.view", "receiving_clerk"),
    ("shipping.view", "production_supervisor"),
    ("shipping.create", "company_admin"),
    ("shipping.create", "receiving_clerk"),
}


@pytest.fixture
async def conn():
    connection = await asyncpg.connect(PG_DSN)
    yield connection
    await connection.close()


def _privileges_required_by_routers() -> set[str]:
    """Every string literal passed to require_privilege / require_any_privilege in app/routers."""
    required: set[str] = set()

    for path in sorted(ROUTERS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name not in ("require_privilege", "require_any_privilege"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    required.add(arg.value)

    return required - _SENTINEL_PRIVILEGES


async def _seeded_privileges(conn) -> set[str]:
    rows = await conn.fetch("SELECT DISTINCT privilege_name FROM role_privilege_assignments")
    return {r["privilege_name"] for r in rows}


def test_router_privileges_are_discoverable():
    """Guard the guard: if the AST walk stops finding privileges, the tests below go vacuous."""
    required = _privileges_required_by_routers()

    assert "shipping.view" in required
    assert "shipping.create" in required
    assert len(required) > 10


async def test_every_router_privilege_is_seeded(conn):
    """A privilege enforced by a router but granted to no role is a permanent 403."""
    required = _privileges_required_by_routers()
    seeded = await _seeded_privileges(conn)

    unseeded = required - seeded - _UNSEEDED_KNOWN_GAPS
    assert not unseeded, (
        f"Privileges enforced by a router but granted to no role: {sorted(unseeded)}. "
        "Add them to the role-privilege seed in a migration."
    )


async def test_known_gaps_are_still_gaps(conn):
    """Retire an allowlist entry once it is seeded, so the list cannot rot into a blind spot."""
    seeded = await _seeded_privileges(conn)

    fixed = _UNSEEDED_KNOWN_GAPS & seeded
    assert not fixed, (
        f"{sorted(fixed)} is seeded now — drop it from _UNSEEDED_KNOWN_GAPS so the guard covers it."
    )


async def test_shipping_privileges_granted_to_expected_roles(conn):
    """The exact ACR-35 mapping, so dropping a role from migration 011 fails loudly."""
    rows = await conn.fetch(
        """
        SELECT a.privilege_name, r.role_name
        FROM role_privilege_assignments a
        JOIN roles r ON r.id = a.role_id
        WHERE a.privilege_name LIKE 'shipping.%'
        """
    )
    granted = {(r["privilege_name"], r["role_name"]) for r in rows}

    assert granted == EXPECTED_SHIPPING_GRANTS


async def test_machine_operator_has_no_shipping_privileges(conn):
    """The operator works a line, not the dock — neither privilege reaches them."""
    rows = await conn.fetch(
        """
        SELECT a.privilege_name
        FROM role_privilege_assignments a
        JOIN roles r ON r.id = a.role_id
        WHERE r.role_name = 'machine_operator' AND a.privilege_name LIKE 'shipping.%'
        """
    )

    assert rows == []
