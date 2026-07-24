"""
ACR-35 — the role-privilege seed must cover every privilege the routers enforce.

`require_privilege` resolves names at request time straight from `role_privilege_assignments`
(`app/core/rbac.py`), so a privilege that no migration grants is not a config gap — it is a
permanent 403 for every user, including `company_admin`. That is exactly how `shipping.view` and
`shipping.create` shipped: enforced by `routers/shipments.py`, granted by nobody.

These tests read the privileges out of the router source and compare them against what the
migrations grant, so the next unseeded privilege fails here rather than in production. The
shipping-specific tests then assert the resulting grants in a live database.

The live tests require a running PostgreSQL database with migrations applied (same as
`test_schema.py`).
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

_BACKEND = Path(__file__).resolve().parent.parent
ROUTERS_DIR = _BACKEND / "app" / "routers"
MIGRATIONS_DIR = _BACKEND / "alembic" / "versions"

# `require_privilege("authenticated")` is the documented escape hatch for "any valid JWT" — it is
# deliberately not a row in the table (see `app/core/rbac.py`).
_SENTINEL_PRIVILEGES = {"authenticated"}

# Privileges enforced by a router that no migration grants. Same defect as ACR-35, different
# privilege: `master_data.*` is required by routers/contacts.py and routers/products.py but seeded
# only by scripts/seed_fake_data.py, so contacts and products 403 on a migrations-only database.
# Tracked separately — deliberately out of ACR-35's scope rather than silently widened into it.
_UNSEEDED_KNOWN_GAPS = {"master_data.view", "master_data.manage"}

# The mapping migration 012 seeds. Mirrors the deliveries.create / deliveries.view split: the clerk
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


def _privileges_granted_by_migrations(candidates: set[str]) -> set[str]:
    """
    Which of `candidates` some migration grants.

    Deliberately reads the migrations rather than the live table: `scripts/seed_fake_data.py`
    grants privileges the migrations never do, so a database built by `reset-db-and-seed.sh` would
    otherwise look complete while a migrations-only database (CI, and any real deployment) 403s.
    Membership is tested against known names rather than extracting unknown ones, so the varied
    seed styles across 002/010/012 all read the same way.
    """
    blob = "\n".join(path.read_text() for path in MIGRATIONS_DIR.glob("*.py"))
    return {name for name in candidates if f"'{name}'" in blob or f'"{name}"' in blob}


def test_router_privileges_are_discoverable():
    """Guard the guard: if the AST walk stops finding privileges, the tests below go vacuous."""
    required = _privileges_required_by_routers()

    assert "shipping.view" in required
    assert "shipping.create" in required
    assert len(required) > 10


def test_every_router_privilege_is_seeded():
    """A privilege enforced by a router but granted by no migration is a permanent 403."""
    required = _privileges_required_by_routers()
    granted = _privileges_granted_by_migrations(required)

    unseeded = required - granted - _UNSEEDED_KNOWN_GAPS
    assert not unseeded, (
        f"Privileges enforced by a router but granted to no role: {sorted(unseeded)}. "
        "Add them to the role-privilege seed in a migration."
    )


def test_known_gaps_are_still_gaps():
    """Retire an allowlist entry once it is seeded, so the list cannot rot into a blind spot."""
    granted = _privileges_granted_by_migrations(_UNSEEDED_KNOWN_GAPS)

    assert not granted, (
        f"{sorted(granted)} is seeded now — drop it from _UNSEEDED_KNOWN_GAPS so the guard covers it."
    )


async def test_shipping_privileges_granted_to_expected_roles(conn):
    """The exact ACR-35 mapping, so dropping a role from migration 012 fails loudly."""
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
