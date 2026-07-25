"""shipment invoices + the price snapshot they are billed from

ACR-33. Two changes to the outbound side:

1. **``shipment_items.unit_price``** — a price snapshot taken at ship time (``products`` has no
   price column and none is planned), which the invoice is billed from.
2. **Invoices** — ``invoices`` + ``invoice_lines``, priced off that snapshot.

The §4.3 vocabulary (``direct_customer`` / ``transfer``) and ``source`` were originally this
ticket's too, but ACR-39 (migration 012) moved every document fact off ``shipments`` and onto the
unified ``delivery_notes`` row, where both now live with their own CHECK constraints. Nothing is
left for this revision to do there.

This revision also used to grant ``shipping.view`` / ``shipping.create`` to ``company_admin`` — a
one-role stopgap, because ``002`` grants them to nobody and every shipment endpoint 403s without
them. ACR-35 (migration 013) now seeds the full role matrix for exactly those two privileges, and
the invoice endpoints reuse them rather than introducing any of their own, so the grant is gone
from here and 013 is its single owner. Seeding it in both places would double-insert.

Revision ID: 014
Revises: 013
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Price snapshot on the shipment line ──────────────────────────────
    op.add_column("shipment_items", sa.Column("unit_price", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_shipment_items_unit_price",
        "shipment_items",
        "unit_price IS NULL OR unit_price >= 0",
    )

    # ── 2. Invoices ─────────────────────────────────────────────────────────
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "shipment_id",
            sa.Integer(),
            sa.ForeignKey("shipments.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("invoice_number", sa.String(50), nullable=False, unique=True),
        sa.Column("invoice_date", sa.String(20), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("subtotal_amount", sa.Integer(), nullable=False),
        sa.Column("tax_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="issued"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("status IN ('issued', 'void')", name="ck_invoices_status"),
        sa.CheckConstraint("subtotal_amount >= 0", name="ck_invoices_subtotal"),
        sa.CheckConstraint("tax_amount >= 0", name="ck_invoices_tax"),
        sa.CheckConstraint("total_amount >= 0", name="ck_invoices_total"),
    )

    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "invoice_id",
            sa.Integer(),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shipment_item_id",
            sa.Integer(),
            sa.ForeignKey("shipment_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("line_total", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_invoice_lines_qty"),
        sa.CheckConstraint("unit_price >= 0", name="ck_invoice_lines_unit_price"),
        sa.CheckConstraint("line_total >= 0", name="ck_invoice_lines_total"),
    )

    op.create_index("ix_invoices_shipment_id", "invoices", ["shipment_id"])
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])


def downgrade():
    op.drop_index("ix_invoice_lines_invoice_id", table_name="invoice_lines")
    op.drop_index("ix_invoices_shipment_id", table_name="invoices")
    op.drop_table("invoice_lines")
    op.drop_table("invoices")

    op.drop_constraint("ck_shipment_items_unit_price", "shipment_items", type_="check")
    op.drop_column("shipment_items", "unit_price")
