"""shipment invoices + Transfer/Direct Customer vocabulary + source

ACR-33. Three changes to the outbound side, plus the privilege grant that makes it reachable:

1. **Vocabulary** — ``shipments.type`` moves from ``customer_order | transfer_out`` to the domain
   model's ``direct_customer | transfer`` (§4.3). Data-preserving and reversible.
2. **``shipments.source``** — nullable, names the originating stock location on a Direct Customer
   note (e.g. ``SC``). Assigned to this ticket by ``reference/target_schema.md`` §4. Legal only on
   a Direct Customer note, enforced by CHECK.
3. **Invoices** — ``invoices`` + ``invoice_lines``, priced off a ``shipment_items.unit_price``
   snapshot taken at ship time (``products`` has no price column and none is planned).

The ``shipping.view`` / ``shipping.create`` grant to ``company_admin`` is a one-role slice of
ACR-35: those privileges are granted to no role in ``002``, so every shipment endpoint 403s and
the module is unreachable. ACR-35 keeps the wider role matrix.

Revision ID: 011
Revises: 010
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. Type vocabulary → domain model §4.3 ──────────────────────────────
    # Drop the constraint first: the UPDATEs below violate it while in flight.
    op.drop_constraint("ck_shipments_type", "shipments", type_="check")
    op.execute("UPDATE shipments SET type = 'direct_customer' WHERE type = 'customer_order'")
    op.execute("UPDATE shipments SET type = 'transfer' WHERE type = 'transfer_out'")
    op.alter_column("shipments", "type", server_default="direct_customer")
    op.create_check_constraint(
        "ck_shipments_type",
        "shipments",
        "type IN ('transfer', 'direct_customer')",
    )

    # ── 2. §4.3 source ──────────────────────────────────────────────────────
    op.add_column("shipments", sa.Column("source", sa.String(50), nullable=True))
    op.create_check_constraint(
        "ck_shipments_source_direct_only",
        "shipments",
        "source IS NULL OR type = 'direct_customer'",
    )

    # ── 3. Price snapshot on the shipment line ──────────────────────────────
    op.add_column("shipment_items", sa.Column("unit_price", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_shipment_items_unit_price",
        "shipment_items",
        "unit_price IS NULL OR unit_price >= 0",
    )

    # ── 4. Invoices ─────────────────────────────────────────────────────────
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

    # ── 5. Make shipping reachable (ACR-35 slice) ───────────────────────────
    op.execute(
        """
        INSERT INTO role_privilege_assignments (role_id, privilege_name)
        SELECT r.id, p.privilege_name
        FROM roles r
        CROSS JOIN (VALUES
            ('shipping.view'),
            ('shipping.create')
        ) AS p(privilege_name)
        WHERE r.role_name = 'company_admin'
        ON CONFLICT DO NOTHING
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM role_privilege_assignments
        WHERE privilege_name IN ('shipping.view', 'shipping.create')
          AND role_id IN (SELECT id FROM roles WHERE role_name = 'company_admin')
        """
    )

    op.drop_index("ix_invoice_lines_invoice_id", table_name="invoice_lines")
    op.drop_index("ix_invoices_shipment_id", table_name="invoices")
    op.drop_table("invoice_lines")
    op.drop_table("invoices")

    op.drop_constraint("ck_shipment_items_unit_price", "shipment_items", type_="check")
    op.drop_column("shipment_items", "unit_price")

    op.drop_constraint("ck_shipments_source_direct_only", "shipments", type_="check")
    op.drop_column("shipments", "source")

    op.drop_constraint("ck_shipments_type", "shipments", type_="check")
    op.execute("UPDATE shipments SET type = 'customer_order' WHERE type = 'direct_customer'")
    op.execute("UPDATE shipments SET type = 'transfer_out' WHERE type = 'transfer'")
    op.alter_column("shipments", "type", server_default="customer_order")
    op.create_check_constraint(
        "ck_shipments_type",
        "shipments",
        "type IN ('customer_order', 'transfer_out')",
    )
