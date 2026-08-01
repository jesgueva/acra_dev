"""Privilege parity invariants (A10-5) — orphaned migration grants, against a live, migrated DB.

Requires a running PostgreSQL with migrations applied — same contract as `tests/test_schema.py`
and the other `tests/integration/` modules.

The "every enforced privilege is granted by a migration" direction already has a test:
``test_shipping_privileges.py::test_every_router_privilege_is_seeded`` (ACR-35), which reads
migration source via AST rather than a live database. This module adds the direction that one
doesn't cover — a privilege a migration grants that no router enforces and no frontend
``PrivilegeGate``/nav item references, i.e. a dead or typo'd grant. ``002``'s
``inventory.alerts.manage`` was exactly this (revoked in ``016``): granted to ``company_admin``
since the very first privilege migration, checked by nothing, ever.

That check needs the actual rows a migration produced, not its source text: migrations grant
privileges through three different code shapes (a static SQL tuple, a Python tuple rendered
per-pair into SQL, a cross-product loop over two tuples), and — as of ``016`` — a fourth shape,
revoking a privilege granted by an *earlier* migration. Reading `role_privilege_assignments` after
`alembic upgrade head` sidesteps all four rather than trying to parse each correctly.

A locally-seeded dev database also has ``scripts/seed_fake_data.py``'s grants layered on top of
the migrations' own. That's fine: ``test_privilege_parity.py`` already asserts every seed grant
corresponds to something enforced or frontend-referenced, so any extra rows a seeded database adds
here are already known-good and cannot produce a false "orphaned grant" failure.
"""
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from app.models.user import RolePrivilegeAssignment
from tests.test_privilege_parity import enforced_privileges, frontend_referenced_privileges

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/acra_db",
)


async def _migration_granted_privileges() -> set[str]:
    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(select(RolePrivilegeAssignment.privilege_name).distinct())
            return {row[0] for row in result}
    finally:
        await engine.dispose()


async def test_no_orphaned_migration_grants():
    used = enforced_privileges() | frontend_referenced_privileges()
    granted = await _migration_granted_privileges()
    orphaned = granted - used
    assert not orphaned, (
        f"privilege(s) {sorted(orphaned)} are granted to a role in the migrated database but no "
        "router ever checks that exact name and no frontend PrivilegeGate/nav item references it "
        "either — likely a typo'd or dead grant (the mirror-image of the bug the other parity "
        "tests catch; 002's since-revoked 'inventory.alerts.manage' was exactly this)."
    )
