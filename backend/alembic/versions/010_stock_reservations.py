"""stock reservations (reserved / available stock)

Adds the ``stock_reservations`` table backing ``available = on_hand - reserved`` per
``(item, state)``, plus the ``inventory.reserve`` privilege grants. Reservations never mutate
``inventory_lots`` and never write an ``inventory_transactions`` row — on-hand only moves at
worksheet close (ACR-31).

Revision ID: 010
Revises: 009
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None

# Roles that run production worksheets, i.e. the ones that reserve stock.
_RESERVE_ROLES = ("company_admin", "production_supervisor")


def upgrade():
    op.create_table(
        "stock_reservations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("state", sa.String(20), nullable=False, server_default="in_storage"),
        sa.Column("quantity", sa.Integer(), nullable=False),
        # Forward reference to ACR-29's production_worksheet_lines — FK added by that ticket.
        sa.Column("production_worksheet_line_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("released_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_stock_reservations_qty"),
        sa.CheckConstraint(
            "status IN ('active', 'released')", name="ck_stock_reservations_status"
        ),
        sa.CheckConstraint(
            "state IN ('in_storage', 'in_production', 'shipped', 'consumed')",
            name="ck_stock_reservations_state",
        ),
    )

    # RSK-04 — the availability aggregation filters on exactly these three columns.
    op.create_index(
        "ix_stock_reservations_item_state",
        "stock_reservations",
        ["product_id", "state", "status"],
    )

    # Seed the new privilege. Without this every reserve endpoint 403s for every user (ACR-35).
    roles_sql = ", ".join(f"('{role}')" for role in _RESERVE_ROLES)
    op.execute(
        f"""
        INSERT INTO role_privilege_assignments (role_id, privilege_name)
        SELECT r.id, 'inventory.reserve'
        FROM roles r
        JOIN (VALUES {roles_sql}) AS p(role_name) ON r.role_name = p.role_name
        """
    )


def downgrade():
    op.execute(
        "DELETE FROM role_privilege_assignments WHERE privilege_name = 'inventory.reserve'"
    )
    op.drop_index("ix_stock_reservations_item_state", table_name="stock_reservations")
    op.drop_table("stock_reservations")
