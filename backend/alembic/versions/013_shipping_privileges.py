"""seed shipping.* privilege grants

``routers/shipments.py`` requires ``shipping.view`` and ``shipping.create``, but migration
``002_role_privilege_assignments`` never granted either to any role — so every shipment endpoint
returned 403 for every user, including ``company_admin``, and the Shipping page was unreachable.

The mapping mirrors the ``deliveries.create`` / ``deliveries.view`` split already seeded in 002:
the clerk works the dock in both directions, the supervisor needs visibility into what shipped,
and the machine operator gets neither.

Revision ID: 013
Revises: 012
Create Date: 2026-07-24
"""
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

_GRANTS = (
    ("company_admin", "shipping.view"),
    ("company_admin", "shipping.create"),
    ("receiving_clerk", "shipping.view"),
    ("receiving_clerk", "shipping.create"),
    ("production_supervisor", "shipping.view"),
)


def upgrade():
    values = ", ".join(f"('{role}', '{privilege}')" for role, privilege in _GRANTS)
    # ON CONFLICT because scripts/seed_fake_data.py also grants these: a developer who seeded
    # before upgrading already has the rows. 010/011 predate that overlap and omit it.
    op.execute(
        f"""
        INSERT INTO role_privilege_assignments (role_id, privilege_name)
        SELECT r.id, p.privilege_name
        FROM roles r
        JOIN (VALUES {values}) AS p(role_name, privilege_name) ON r.role_name = p.role_name
        ON CONFLICT (role_id, privilege_name) DO NOTHING
        """
    )


def downgrade():
    privileges_sql = ", ".join(f"'{privilege}'" for privilege in sorted({p for _, p in _GRANTS}))
    op.execute(
        f"DELETE FROM role_privilege_assignments WHERE privilege_name IN ({privileges_sql})"
    )
