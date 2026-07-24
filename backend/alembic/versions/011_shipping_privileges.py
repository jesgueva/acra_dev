"""seed shipping.* privilege grants

``routers/shipments.py`` requires ``shipping.view`` and ``shipping.create``, but migration
``002_role_privilege_assignments`` never granted either to any role — so every shipment endpoint
returned 403 for every user, including ``company_admin``, and the Shipping page was unreachable.

The mapping mirrors the ``deliveries.create`` / ``deliveries.view`` split already seeded in 002:
the clerk works the dock in both directions, the supervisor needs visibility into what shipped,
and the machine operator gets neither.

Revision ID: 011
Revises: 010
Create Date: 2026-07-24
"""
from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None

# Dispatch is a dock function; the supervisor sees outbound stock leave but does not book it.
_PRIVILEGE_ROLES = {
    "shipping.view": ("company_admin", "receiving_clerk", "production_supervisor"),
    "shipping.create": ("company_admin", "receiving_clerk"),
}


def upgrade():
    for privilege, roles in _PRIVILEGE_ROLES.items():
        roles_sql = ", ".join(f"('{role}')" for role in roles)
        # ON CONFLICT keeps this safe to re-run after a partial rollback — the target is the
        # (role_id, privilege_name) primary key from migration 002.
        op.execute(
            f"""
            INSERT INTO role_privilege_assignments (role_id, privilege_name)
            SELECT r.id, '{privilege}'
            FROM roles r
            JOIN (VALUES {roles_sql}) AS p(role_name) ON r.role_name = p.role_name
            ON CONFLICT (role_id, privilege_name) DO NOTHING
            """
        )


def downgrade():
    privileges_sql = ", ".join(f"'{privilege}'" for privilege in _PRIVILEGE_ROLES)
    op.execute(
        f"DELETE FROM role_privilege_assignments WHERE privilege_name IN ({privileges_sql})"
    )
