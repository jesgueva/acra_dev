"""shipments

Revision ID: 008
Revises: 007
Create Date: 2026-04-09
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("carrier_id", sa.Integer(), sa.ForeignKey("contacts.id"), nullable=True),
        sa.Column("bol_number", sa.String(100), nullable=False),
        sa.Column("shipment_date", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "type",
            sa.String(30),
            nullable=False,
            server_default="customer_order",
        ),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "type IN ('customer_order', 'transfer_out')",
            name="ck_shipments_type",
        ),
    )

    op.create_table(
        "shipment_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "shipment_id",
            sa.Integer(),
            sa.ForeignKey("shipments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lot_id", sa.Integer(), sa.ForeignKey("inventory_lots.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_shipment_items_qty"),
    )

    op.create_index("ix_shipments_contact_id", "shipments", ["contact_id"])
    op.create_index("ix_shipments_shipment_date", "shipments", ["shipment_date"])
    op.create_index("ix_shipment_items_shipment_id", "shipment_items", ["shipment_id"])
    op.create_index("ix_shipment_items_lot_id", "shipment_items", ["lot_id"])


def downgrade():
    op.drop_index("ix_shipment_items_lot_id", table_name="shipment_items")
    op.drop_index("ix_shipment_items_shipment_id", table_name="shipment_items")
    op.drop_index("ix_shipments_shipment_date", table_name="shipments")
    op.drop_index("ix_shipments_contact_id", table_name="shipments")
    op.drop_table("shipment_items")
    op.drop_table("shipments")
