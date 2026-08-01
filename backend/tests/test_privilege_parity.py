"""Privilege parity invariants (A10-5) — seed side.

These tests read repo files rather than exercising ``app.*``. They exist because privilege names
have already drifted from what routers enforce, twice — ``013_shipping_privileges`` records that
``shipping.view``/``shipping.create`` were enforced but granted to no role until that migration
landed, and ``016_master_data_view_privilege`` found the same defect for ``master_data.view``,
``master_data.manage``, plus a dead, never-enforced ``inventory.alerts.manage`` grant running the
other direction. A third, independent drift source was ``backend/scripts/create_admin.py``, which
granted privilege names like ``work_order.view`` and ``delivery.edit`` that never matched any
real, enforced name at all — deleted rather than fixed, since ``seed_fake_data.py`` already covers
the same need correctly.

The migration side of the same check — every enforced privilege is granted by the Alembic
migrations, and every migration grant corresponds to something actually enforced — lives in
``tests/integration/test_privilege_parity_migrations.py`` instead: migrations grant privileges
through three different code shapes (a static SQL tuple, a Python tuple rendered per-pair into
SQL, a cross-product loop over two tuples), so the only reliable source of truth for "what a
migration actually grants" is the database it produces, not a regex over its source.

The checks here need only ``scripts/seed_fake_data.py`` (a plain, safely-importable Python dict)
and the router/frontend source, so no database and no fixtures — they run in milliseconds as part
of the normal suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
ROUTERS_DIR = BACKEND_DIR / "app" / "routers"
SEED_SCRIPT = BACKEND_DIR / "scripts" / "seed_fake_data.py"
FRONTEND_DIR = REPO_ROOT / "frontend"
FRONTEND_PRIVILEGES_TS = FRONTEND_DIR / "src" / "lib" / "privileges.ts"

# The backend container image is built with backend/ as its context (see test_packaging.py), so
# frontend/ simply is not there. Skip the frontend-aware checks rather than fail in that
# environment — they still run on a developer checkout and in CI.
FRONTEND_AVAILABLE = FRONTEND_PRIVILEGES_TS.is_file()
requires_frontend = pytest.mark.skipif(
    not FRONTEND_AVAILABLE, reason="frontend/ is absent (running inside the backend image)"
)

# ``require_privilege("authenticated")`` is a special case handled entirely inside
# ``app.core.rbac`` — it skips the privilege-membership check rather than looking up a row in
# ``role_privilege_assignments``, so it is never something a migration or the seed script grants.
AUTHENTICATED = "authenticated"

_REQUIRE_PRIVILEGE = re.compile(r'require_privilege\(\s*"([^"]+)"\s*\)')
_REQUIRE_ANY_PRIVILEGE = re.compile(r'require_any_privilege\(\s*((?:"[^"]+"\s*,?\s*)+)\)')
_QUOTED = re.compile(r'"([^"]+)"')
_TS_PRIVILEGE_CONST = re.compile(r'(\w+):\s*"([^"]+)"')
_TS_PRIVILEGE_USAGE = re.compile(r"PRIVILEGES\.(\w+)")


def enforced_privileges() -> set[str]:
    """Every privilege literal checked by a router, across every ``require*privilege`` call.

    Shared with ``tests/integration/test_privilege_parity_migrations.py`` — imported from here
    rather than duplicated so the two halves of the parity check can never read the enforced set
    differently.
    """
    privileges: set[str] = set()
    for path in ROUTERS_DIR.glob("*.py"):
        text = path.read_text()
        privileges.update(_REQUIRE_PRIVILEGE.findall(text))
        for group in _REQUIRE_ANY_PRIVILEGE.findall(text):
            privileges.update(_QUOTED.findall(group))
    privileges.discard(AUTHENTICATED)
    assert privileges, "no require_privilege(...) calls found — routers glob is probably wrong"
    return privileges


def _seed_granted_privileges() -> set[str]:
    """Every privilege granted to any role in ``seed_fake_data.py``'s ``ROLE_DEFINITIONS``."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("seed_fake_data", SEED_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    privileges: set[str] = set()
    for definition in module.ROLE_DEFINITIONS.values():
        privileges.update(definition["privileges"])
    privileges.discard(AUTHENTICATED)
    return privileges


def frontend_referenced_privileges() -> set[str]:
    """Privilege values behind every ``PRIVILEGES.<NAME>`` reference anywhere in ``frontend/``.

    Some privileges (e.g. ``receiving.view``) gate a page or nav item client-side via
    ``PrivilegeGate``/``navItems.ts`` with no corresponding backend ``require_privilege(...)``
    call — that is a legitimate, frontend-only use, not an orphaned grant, so it must count as
    "used" alongside the backend-enforced set. Shared with the migrations-side test for the same
    reason as ``enforced_privileges``.
    """
    name_to_value = dict(_TS_PRIVILEGE_CONST.findall(FRONTEND_PRIVILEGES_TS.read_text()))
    referenced_names: set[str] = set()
    for path in FRONTEND_DIR.rglob("*.ts*"):
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        referenced_names.update(_TS_PRIVILEGE_USAGE.findall(path.read_text()))
    return {name_to_value[name] for name in referenced_names if name in name_to_value}


# --------------------------------------------------------------------------- tests


def test_every_enforced_privilege_is_granted_by_seed():
    enforced = enforced_privileges()
    granted = _seed_granted_privileges()
    missing = enforced - granted
    assert not missing, (
        f"privilege(s) {sorted(missing)} are required by a router's require_privilege(...) / "
        "require_any_privilege(...) but scripts/seed_fake_data.py never grants them to any role "
        "in ROLE_DEFINITIONS — every locally-seeded demo user would 403 on that endpoint."
    )


@requires_frontend
def test_no_orphaned_seed_grants():
    used = enforced_privileges() | frontend_referenced_privileges()
    granted = _seed_granted_privileges()
    orphaned = granted - used
    assert not orphaned, (
        f"privilege(s) {sorted(orphaned)} are granted to a role in scripts/seed_fake_data.py but "
        "no router ever checks that exact name and no frontend PrivilegeGate/nav item references "
        "it either — likely a typo'd grant."
    )
