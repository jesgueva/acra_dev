"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-04-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("user_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(50), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(150), nullable=False),
        sa.Column(
            "preferred_language",
            sa.String(10),
            nullable=False,
            server_default="en",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_users_status"),
    )

    # 2. roles
    op.create_table(
        "roles",
        sa.Column("role_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("role_name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.execute(
        """
        INSERT INTO roles (role_name, description) VALUES
            ('company_admin',         'Full system access; manages users, settings, work orders, and all reports.'),
            ('receiving_clerk',       'Logs incoming material deliveries and performs OCR scanning.'),
            ('production_supervisor', 'Prioritizes and plans work orders, assigns production lines, monitors active orders.'),
            ('machine_operator',      'Views active work orders assigned to their production line.')
        """
    )

    # 3. user_role_assignments
    op.create_table(
        "user_role_assignments",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("roles.role_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    # 4. deliveries
    op.create_table(
        "deliveries",
        sa.Column("delivery_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("supplier", sa.String(200), nullable=False),
        sa.Column("carrier", sa.String(200), nullable=False),
        sa.Column("delivery_date", sa.Date(), nullable=False),
        sa.Column("bol_reference", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # 5. inventory_items (source_delivery_item_id FK added after delivery_items is created)
    op.create_table(
        "inventory_items",
        sa.Column("inventory_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("material_type", sa.String(200), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column(
            "quantity_on_hand",
            sa.Numeric(12, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column("lot_batch_number", sa.String(100), nullable=False),
        sa.Column("storage_location", sa.String(100), nullable=False),
        sa.Column("source_delivery_item_id", sa.Integer(), nullable=True),
        sa.Column(
            "last_updated",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "category IN ('raw', 'finished')", name="ck_inventory_items_category"
        ),
        sa.CheckConstraint(
            "quantity_on_hand >= 0", name="ck_inventory_items_qty"
        ),
    )

    # 6. delivery_items (references deliveries and inventory_items)
    op.create_table(
        "delivery_items",
        sa.Column("item_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "delivery_id",
            sa.Integer(),
            sa.ForeignKey("deliveries.delivery_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("material_type", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("lot_batch_number", sa.String(100), nullable=False),
        sa.Column("storage_location", sa.String(100), nullable=False),
        sa.Column(
            "inventory_item_id",
            sa.Integer(),
            sa.ForeignKey("inventory_items.inventory_id"),
            nullable=True,
        ),
        sa.CheckConstraint("quantity > 0", name="ck_delivery_items_quantity"),
    )

    # Add the circular FK: inventory_items.source_delivery_item_id → delivery_items.item_id
    op.create_foreign_key(
        "fk_inventory_items_source_delivery",
        "inventory_items",
        "delivery_items",
        ["source_delivery_item_id"],
        ["item_id"],
    )

    # 7. work_orders
    op.create_table(
        "work_orders",
        sa.Column("work_order_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("product", sa.String(200), nullable=False),
        sa.Column("quantity_required", sa.Numeric(12, 3), nullable=False),
        sa.Column(
            "quantity_produced",
            sa.Numeric(12, 3),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "priority",
            sa.String(20),
            nullable=False,
            server_default="medium",
        ),
        sa.Column(
            "display_sequence",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default="created",
        ),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("production_line", sa.String(50), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "quantity_required > 0", name="ck_work_orders_qty_required"
        ),
        sa.CheckConstraint(
            "quantity_produced >= 0", name="ck_work_orders_qty_produced"
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="ck_work_orders_priority",
        ),
        sa.CheckConstraint(
            "status IN ('created', 'materials_allocated', 'in_production', 'completed', 'ready_for_shipment')",
            name="ck_work_orders_status",
        ),
    )

    # 8. work_order_materials
    op.create_table(
        "work_order_materials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "work_order_id",
            sa.Integer(),
            sa.ForeignKey("work_orders.work_order_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("material_type", sa.String(200), nullable=False),
        sa.Column("quantity_required", sa.Numeric(12, 3), nullable=False),
        sa.Column(
            "quantity_allocated",
            sa.Numeric(12, 3),
            nullable=False,
            server_default="0",
        ),
        sa.CheckConstraint(
            "quantity_required > 0", name="ck_wom_qty_required"
        ),
        sa.CheckConstraint(
            "quantity_allocated >= 0", name="ck_wom_qty_allocated"
        ),
    )

    # 9. material_allocations
    op.create_table(
        "material_allocations",
        sa.Column(
            "allocation_id", sa.Integer(), primary_key=True, autoincrement=True
        ),
        sa.Column(
            "work_order_material_id",
            sa.Integer(),
            sa.ForeignKey("work_order_materials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "inventory_id",
            sa.Integer(),
            sa.ForeignKey("inventory_items.inventory_id"),
            nullable=False,
        ),
        sa.Column("lot_batch_number", sa.String(100), nullable=False),
        sa.Column("quantity_allocated", sa.Numeric(12, 3), nullable=False),
        sa.Column(
            "allocated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "quantity_allocated > 0", name="ck_material_allocations_qty"
        ),
    )

    # 10. audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("log_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.user_id"),
            nullable=True,
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index("idx_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("idx_audit_logs_user", "audit_logs", ["user_id"])
    op.create_index(
        "idx_audit_logs_time",
        "audit_logs",
        [sa.text("timestamp DESC")],
    )

    # 11. low_stock_alerts
    op.create_table(
        "low_stock_alerts",
        sa.Column("alert_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("material_type", sa.String(200), nullable=False, unique=True),
        sa.Column("threshold", sa.Numeric(12, 3), nullable=False),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.CheckConstraint("threshold >= 0", name="ck_low_stock_alerts_threshold"),
    )


def downgrade() -> None:
    op.drop_table("low_stock_alerts")
    op.drop_index("idx_audit_logs_time", table_name="audit_logs")
    op.drop_index("idx_audit_logs_user", table_name="audit_logs")
    op.drop_index("idx_audit_logs_entity", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("material_allocations")
    op.drop_table("work_order_materials")
    op.drop_table("work_orders")
    op.drop_constraint(
        "fk_inventory_items_source_delivery", "inventory_items", type_="foreignkey"
    )
    op.drop_table("delivery_items")
    op.drop_table("inventory_items")
    op.drop_table("deliveries")
    op.drop_table("user_role_assignments")
    op.drop_table("roles")
    op.drop_table("users")
