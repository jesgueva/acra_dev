"""delivery items v2 — item_name rename, new BOL fields, notes, leftover

Revision ID: 004
Revises: 003
Create Date: 2026-04-09

Changes:
- deliveries: add notes column
- delivery_items: rename material_type→item_name, drop lot_batch_number+storage_location,
  add description/pallets/units_per_pallet/leftover, drop bol_reference unique constraint
- inventory_items: rename material_type→item_name, make lot_batch_number+storage_location nullable
- low_stock_alerts: rename material_type→item_name
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── deliveries ────────────────────────────────────────────────────────────
    op.add_column("deliveries", sa.Column("notes", sa.Text(), nullable=True))
    op.alter_column(
        "deliveries",
        "delivery_date",
        existing_type=sa.Date(),
        type_=sa.String(20),
        postgresql_using="delivery_date::text",
    )
    op.drop_constraint("deliveries_bol_reference_key", "deliveries", type_="unique")

    # ── delivery_items ────────────────────────────────────────────────────────
    op.alter_column("delivery_items", "material_type", new_column_name="item_name")
    op.drop_column("delivery_items", "lot_batch_number")
    op.drop_column("delivery_items", "storage_location")
    op.add_column("delivery_items", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("delivery_items", sa.Column("pallets", sa.Integer(), nullable=True))
    op.add_column("delivery_items", sa.Column("units_per_pallet", sa.Integer(), nullable=True))
    op.add_column("delivery_items", sa.Column("leftover", sa.Numeric(12, 3), nullable=True))

    # ── inventory_items ───────────────────────────────────────────────────────
    op.alter_column("inventory_items", "material_type", new_column_name="item_name")
    op.alter_column(
        "inventory_items",
        "lot_batch_number",
        existing_type=sa.String(100),
        nullable=True,
    )
    op.alter_column(
        "inventory_items",
        "storage_location",
        existing_type=sa.String(100),
        nullable=True,
    )

    # ── low_stock_alerts ──────────────────────────────────────────────────────
    op.alter_column("low_stock_alerts", "material_type", new_column_name="item_name")

    # ── material_allocations ──────────────────────────────────────────────────
    op.alter_column(
        "material_allocations",
        "lot_batch_number",
        existing_type=sa.String(100),
        nullable=True,
    )


def downgrade() -> None:
    # low_stock_alerts
    op.alter_column("low_stock_alerts", "item_name", new_column_name="material_type")

    # inventory_items
    op.alter_column(
        "inventory_items",
        "lot_batch_number",
        existing_type=sa.String(100),
        nullable=False,
    )
    op.alter_column(
        "inventory_items",
        "storage_location",
        existing_type=sa.String(100),
        nullable=False,
    )
    op.alter_column("inventory_items", "item_name", new_column_name="material_type")

    # delivery_items
    op.drop_column("delivery_items", "leftover")
    op.drop_column("delivery_items", "units_per_pallet")
    op.drop_column("delivery_items", "pallets")
    op.drop_column("delivery_items", "description")
    op.add_column(
        "delivery_items",
        sa.Column("storage_location", sa.String(100), nullable=False, server_default=""),
    )
    op.add_column(
        "delivery_items",
        sa.Column("lot_batch_number", sa.String(100), nullable=False, server_default=""),
    )
    op.alter_column("delivery_items", "item_name", new_column_name="material_type")

    # deliveries
    op.create_unique_constraint(
        "deliveries_bol_reference_key", "deliveries", ["bol_reference"]
    )
    op.alter_column(
        "deliveries",
        "delivery_date",
        existing_type=sa.String(20),
        type_=sa.Date(),
        postgresql_using="delivery_date::date",
    )
    op.drop_column("deliveries", "notes")
