"""add role_privilege_assignments table

Revision ID: 002
Revises: 001
Create Date: 2026-04-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "role_privilege_assignments",
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("privilege_name", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("role_id", "privilege_name"),
    )
    op.create_index(
        "idx_rpa_role_id",
        "role_privilege_assignments",
        ["role_id"],
    )

    # Seed privileges per role
    op.execute(
        """
        INSERT INTO role_privilege_assignments (role_id, privilege_name)
        SELECT r.id, p.privilege_name
        FROM roles r
        CROSS JOIN (VALUES
            ('company_admin',         'users.manage'),
            ('company_admin',         'audit.view'),
            ('company_admin',         'deliveries.create'),
            ('company_admin',         'deliveries.view'),
            ('company_admin',         'inventory.view'),
            ('company_admin',         'inventory.adjust'),
            ('company_admin',         'inventory.alerts.manage'),
            ('company_admin',         'work_orders.create'),
            ('company_admin',         'work_orders.view'),
            ('company_admin',         'work_orders.assign'),
            ('company_admin',         'work_orders.status_update'),
            ('company_admin',         'work_orders.sequence'),
            ('company_admin',         'work_orders.allocate'),
            ('receiving_clerk',       'deliveries.create'),
            ('receiving_clerk',       'deliveries.view'),
            ('receiving_clerk',       'inventory.view'),
            ('production_supervisor', 'deliveries.view'),
            ('production_supervisor', 'inventory.view'),
            ('production_supervisor', 'work_orders.create'),
            ('production_supervisor', 'work_orders.view'),
            ('production_supervisor', 'work_orders.assign'),
            ('production_supervisor', 'work_orders.status_update'),
            ('production_supervisor', 'work_orders.sequence'),
            ('production_supervisor', 'work_orders.allocate'),
            ('machine_operator',      'work_orders.view')
        ) AS p(role_name, privilege_name)
        WHERE r.role_name = p.role_name
        """
    )


def downgrade() -> None:
    op.drop_index("idx_rpa_role_id", table_name="role_privilege_assignments")
    op.drop_table("role_privilege_assignments")
