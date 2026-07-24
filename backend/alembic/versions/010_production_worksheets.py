"""production worksheets — minimal tables for the concurrency-safe close spike (ACR-30)

Adds ``production_worksheets`` and ``production_worksheet_lines``, the smallest shape that lets a
"close" consume stock and therefore be raced against itself (RSK-01 / TC-02).

The load-bearing column is ``production_worksheets.version``: the close guards on it with a single
atomic ``UPDATE ... WHERE id = :id AND version = :expected``, so the winner of a concurrent race is
picked by the database rather than by a read-then-check.

Deliberately narrow — ACR-29 (create-from-WO + reserve) extends these tables additively rather than
replacing them. No ``state`` column on lines: stock is drawn from ``inventory_lots`` by product, so
the spike stays clear of the ``StockState`` vocabulary ACR-26 is still reconciling.

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

# Roles that run production worksheets, i.e. the ones allowed to close one.
_WORKSHEET_ROLES = ("company_admin", "production_supervisor")
_WORKSHEET_PRIVILEGES = (
    "production.worksheet.view",
    "production.worksheet.create",
    "production.worksheet.close",
)


def upgrade():
    op.create_table(
        "production_worksheets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # Nullable for the spike; ACR-29 makes the work order the driver of creation.
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=True),
        sa.Column("production_line", sa.String(100), nullable=True),
        sa.Column("scheduled_date", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        # Optimistic concurrency guard — bumped by exactly one winning close.
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        # ACR-29 adds 'reserved' to this list when reservations land.
        sa.CheckConstraint(
            "status IN ('draft', 'in_progress', 'closed')",
            name="ck_production_worksheets_status",
        ),
        sa.CheckConstraint("version >= 0", name="ck_production_worksheets_version"),
    )

    op.create_table(
        "production_worksheet_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "worksheet_id",
            sa.Integer(),
            sa.ForeignKey("production_worksheets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("planned_quantity", sa.Integer(), nullable=False),  # ×100
        sa.Column("actual_quantity", sa.Integer(), nullable=True),  # ×100, set at close
        sa.CheckConstraint("planned_quantity > 0", name="ck_pw_lines_planned_qty"),
        sa.CheckConstraint(
            "actual_quantity IS NULL OR actual_quantity >= 0", name="ck_pw_lines_actual_qty"
        ),
    )
    op.create_index(
        "ix_pw_lines_worksheet", "production_worksheet_lines", ["worksheet_id"]
    )

    # Seed the privileges. Without this every worksheet endpoint 403s for every user.
    values = ", ".join(
        f"('{role}', '{priv}')"
        for role in _WORKSHEET_ROLES
        for priv in _WORKSHEET_PRIVILEGES
    )
    op.execute(
        f"""
        INSERT INTO role_privilege_assignments (role_id, privilege_name)
        SELECT r.id, p.privilege_name
        FROM roles r
        JOIN (VALUES {values}) AS p(role_name, privilege_name) ON r.role_name = p.role_name
        """
    )


def downgrade():
    privileges = ", ".join(f"'{p}'" for p in _WORKSHEET_PRIVILEGES)
    op.execute(
        f"DELETE FROM role_privilege_assignments WHERE privilege_name IN ({privileges})"
    )
    op.drop_index("ix_pw_lines_worksheet", table_name="production_worksheet_lines")
    op.drop_table("production_worksheet_lines")
    op.drop_table("production_worksheets")
