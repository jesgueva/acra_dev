"""production worksheets — minimal close surface for the ACR-30 concurrency spike

Creates `production_worksheets` + `production_worksheet_lines` with only the columns the
concurrency-safe close protocol needs, plus the three `production.worksheet.*` privileges.

`version` is the optimistic guard: the close claims the worksheet with a single conditional
UPDATE (`WHERE id = :id AND version = :expected AND status <> 'closed'`), so the winner of a
concurrent race is decided atomically by the database rather than by a read-then-check.

ACR-29 (create-from-WO + reserve) extends these tables additively — it adds `work_order_id`
exploding behaviour, the `reserved` status and the reservation FKs. Deliberately **no** `state`
column on lines: the StockState vocabulary is being replaced under ACR-26, and keeping it out is
what stops this branch from acquiring that conflict (see plans/plan_ticket_30.md §9.2).

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


_PRIVILEGES = (
    "production.worksheet.view",
    "production.worksheet.create",
    "production.worksheet.close",
)
_ROLES = ("company_admin", "production_supervisor")

# Single source of truth: upgrade() seeds exactly what downgrade() removes. Spelling the names
# out twice is how a later grant survives `alembic downgrade` as an orphaned row.
_GRANT_VALUES = ",\n            ".join(
    f"('{role}', '{privilege}')" for role in _ROLES for privilege in _PRIVILEGES
)


def upgrade():
    op.create_table(
        "production_worksheets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id"), nullable=True),
        sa.Column("production_line", sa.String(100), nullable=True),
        sa.Column("scheduled_date", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
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
        sa.Column("actual_quantity", sa.Integer(), nullable=True),    # ×100, set at close
        sa.CheckConstraint("planned_quantity > 0", name="ck_pwl_planned_qty"),
        sa.CheckConstraint(
            "actual_quantity IS NULL OR actual_quantity >= 0",
            name="ck_pwl_actual_qty",
        ),
    )

    op.create_index("ix_pw_work_order_id", "production_worksheets", ["work_order_id"])
    op.create_index("ix_pw_status", "production_worksheets", ["status"])
    op.create_index("ix_pwl_worksheet_id", "production_worksheet_lines", ["worksheet_id"])
    op.create_index("ix_pwl_product_id", "production_worksheet_lines", ["product_id"])

    op.execute(
        f"""
        INSERT INTO role_privilege_assignments (role_id, privilege_name)
        SELECT r.id, p.privilege_name
        FROM roles r
        CROSS JOIN (VALUES
            {_GRANT_VALUES}
        ) AS p(role_name, privilege_name)
        WHERE r.role_name = p.role_name
        """
    )


def downgrade():
    op.execute(
        "DELETE FROM role_privilege_assignments WHERE privilege_name IN ("
        + ", ".join(f"'{p}'" for p in _PRIVILEGES)
        + ")"
    )
    op.drop_index("ix_pwl_product_id", table_name="production_worksheet_lines")
    op.drop_index("ix_pwl_worksheet_id", table_name="production_worksheet_lines")
    op.drop_index("ix_pw_status", table_name="production_worksheets")
    op.drop_index("ix_pw_work_order_id", table_name="production_worksheets")
    op.drop_table("production_worksheet_lines")
    op.drop_table("production_worksheets")
