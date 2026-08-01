"""master_data privilege parity fixes (ACR-40, A10-5)

Three drift bugs found while writing ``backend/tests/test_privilege_parity.py`` (A10-5), the same
class of defect ``013_shipping_privileges`` already fixed once for ``shipping.*``:

1. ``routers/contacts.py`` and ``routers/products.py`` require ``master_data.view`` on their
   single-record GET endpoints, but no migration has ever granted it to any role — not even
   ``company_admin``. The list endpoints have a ``master_data.view`` OR ``deliveries.create``
   fallback that happens to mask this for roles holding the latter, but ``GET /contacts/{id}`` and
   ``GET /products/{id}`` 403 for every role today, including ``company_admin``.
2. Same routers require ``master_data.manage`` on their create/update/delete endpoints. It *is*
   granted in ``scripts/seed_fake_data.py``, but no migration grants it — so a fresh, non-seeded
   deployment can create a `company_admin` who can view the master-data list but never edit it.
3. Migration ``002_role_privilege_assignments`` granted ``company_admin`` an
   ``inventory.alerts.manage`` privilege that no router has ever checked — the low-stock-alert
   endpoints (``routers/inventory.py``) are gated on the ordinary ``inventory.view`` /
   ``inventory.adjust`` privileges instead. It has no frontend reference either. Revoked as dead
   weight rather than left to accumulate meaning nobody intended.

Revision ID: 016
Revises: 015
Create Date: 2026-08-01
"""
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

_GRANTS = (
    ("company_admin", "master_data.view"),
    ("company_admin", "master_data.manage"),
)
_REVOKES = (("company_admin", "inventory.alerts.manage"),)


def upgrade():
    values = ", ".join(f"('{role}', '{privilege}')" for role, privilege in _GRANTS)
    # ON CONFLICT because scripts/seed_fake_data.py also grants master_data.manage: a developer
    # who seeded before upgrading already has that row.
    op.execute(
        f"""
        INSERT INTO role_privilege_assignments (role_id, privilege_name)
        SELECT r.id, p.privilege_name
        FROM roles r
        JOIN (VALUES {values}) AS p(role_name, privilege_name) ON r.role_name = p.role_name
        ON CONFLICT (role_id, privilege_name) DO NOTHING
        """
    )
    revoke_privileges = ", ".join(f"'{privilege}'" for _, privilege in _REVOKES)
    op.execute(
        f"DELETE FROM role_privilege_assignments WHERE privilege_name IN ({revoke_privileges})"
    )


def downgrade():
    revoke_values = ", ".join(f"('{role}', '{privilege}')" for role, privilege in _REVOKES)
    op.execute(
        f"""
        INSERT INTO role_privilege_assignments (role_id, privilege_name)
        SELECT r.id, p.privilege_name
        FROM roles r
        JOIN (VALUES {revoke_values}) AS p(role_name, privilege_name) ON r.role_name = p.role_name
        ON CONFLICT (role_id, privilege_name) DO NOTHING
        """
    )
    grant_privileges = ", ".join(f"'{privilege}'" for _, privilege in _GRANTS)
    op.execute(
        f"DELETE FROM role_privilege_assignments WHERE privilege_name IN ({grant_privileges})"
    )
