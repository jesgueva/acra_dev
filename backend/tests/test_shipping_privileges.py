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
from pathlib import Path

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

# The mapping migration 012 seeds, restated rather than imported so a bad edit there fails here.
EXPECTED_SHIPPING_GRANTS = {
    ("shipping.view", "company_admin"),
    ("shipping.view", "receiving_clerk"),
    ("shipping.view", "production_supervisor"),
    ("shipping.create", "company_admin"),
    ("shipping.create", "receiving_clerk"),
}


def _privilege_requirements() -> list[frozenset[str]]:
    """One entry per router dependency, holding the privileges that satisfy it (any one will do)."""
    requirements: list[frozenset[str]] = []

    for path in sorted(ROUTERS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name not in ("require_privilege", "require_any_privilege"):
                continue
            names = {
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            }
            names -= _SENTINEL_PRIVILEGES
            if names:
                requirements.append(frozenset(names))

    return requirements


def _privileges_required_by_routers() -> set[str]:
    """Every privilege name any router mentions, regardless of how it is combined."""
    return set().union(*_privilege_requirements())


def _grant_side_source(path: Path) -> str:
    """A migration's source with its `downgrade()` body removed.

    Every migration names its privileges twice — granted in `upgrade()`, revoked in `downgrade()`
    — so scanning whole files would credit a revoke-only migration as a grant. Dropping just the
    `downgrade` body is the coarse-but-honest cut: migrations hold their names in module-level
    constants (010/011/012), so keeping only `upgrade()` would miss the real grants.
    """
    lines = path.read_text().splitlines()
    for node in ast.parse("\n".join(lines), filename=str(path)).body:
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            del lines[node.lineno - 1 : node.end_lineno]
            break
    return "\n".join(lines)


def _privileges_granted_by_migrations(candidates: set[str]) -> set[str]:
    """
    Which of `candidates` are named on the granting side of some migration.

    Deliberately reads the migrations rather than the live table: `scripts/seed_fake_data.py`
    grants privileges the migrations never do, so a database built by `reset-db-and-seed.sh` would
    look complete while a migrations-only database (CI, and any real deployment) 403s.

    This is a name-mention check, not SQL analysis — it catches the failure that actually happens
    (a privilege enforced by a router that no migration ever mentions), not a migration that names
    a privilege without really granting it.
    """
    blob = "\n".join(_grant_side_source(path) for path in MIGRATIONS_DIR.glob("*.py"))
    return {name for name in candidates if f"'{name}'" in blob or f'"{name}"' in blob}


def test_router_privileges_are_discoverable():
    """Guard the guard: if the AST walk stops finding privileges, the tests below go vacuous."""
    required = _privileges_required_by_routers()

    assert "shipping.view" in required
    assert "shipping.create" in required
    assert len(required) > 10


def test_every_router_privilege_is_seeded():
    """An endpoint no grant can open is a permanent 403 — exactly the ACR-35 defect."""
    requirements = _privilege_requirements()
    granted = _privileges_granted_by_migrations(_privileges_required_by_routers())

    unreachable = [
        req for req in requirements if not (req & granted) and not (req <= _UNSEEDED_KNOWN_GAPS)
    ]
    assert not unreachable, (
        "Endpoints whose privileges are granted to no role: "
        f"{sorted(sorted(req) for req in unreachable)}. "
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

    # Exact equality, so an extra grant fails too — notably machine_operator, who works a line
    # rather than the dock and must reach neither privilege.
    assert granted == EXPECTED_SHIPPING_GRANTS
