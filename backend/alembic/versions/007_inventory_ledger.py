"""inventory ledger — rename inventory_items → inventory_lots, add transactions

Revision ID: 007
Revises: 006
Create Date: 2026-04-09
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # ── 1. Rename table ────────────────────────────────────────────────────────
    op.rename_table("inventory_items", "inventory_lots")

    # ── 2. Drop old check constraints (reference old column names) ─────────────
    op.drop_constraint("ck_inventory_items_category", "inventory_lots", type_="check")
    op.drop_constraint("ck_inventory_items_qty", "inventory_lots", type_="check")

    # ── 3. Add new columns ─────────────────────────────────────────────────────
    op.add_column("inventory_lots", sa.Column("product_id", sa.Integer(), nullable=True))
    op.add_column("inventory_lots", sa.Column("status", sa.String(20), nullable=True))
    op.add_column("inventory_lots", sa.Column("pallet_number", sa.Integer(), nullable=True))

    # ── 4. Rename lot_batch_number → lot_number ────────────────────────────────
    op.alter_column("inventory_lots", "lot_batch_number", new_column_name="lot_number")

    # ── 5. Backfill product_id from products by name match ─────────────────────
    conn.execute(sa.text("""
        UPDATE inventory_lots il
        SET product_id = p.id
        FROM products p
        WHERE il.item_name = p.name
    """))

    # ── 6. Backfill status ─────────────────────────────────────────────────────
    conn.execute(sa.text("UPDATE inventory_lots SET status = 'in_storage'"))

    # ── 7. Convert quantity_on_hand: Numeric → Integer ×100 ───────────────────
    op.alter_column(
        "inventory_lots",
        "quantity_on_hand",
        type_=sa.Integer(),
        nullable=False,
        server_default="0",
        postgresql_using="ROUND(quantity_on_hand * 100)::integer",
    )

    # ── 8. Make status NOT NULL now that it's backfilled ──────────────────────
    op.alter_column("inventory_lots", "status", nullable=False)

    # ── 9. Add FK: inventory_lots.product_id → products.id ────────────────────
    op.create_foreign_key(
        "fk_inventory_lots_product_id", "inventory_lots", "products", ["product_id"], ["id"]
    )

    # ── 10. Add new check constraints ─────────────────────────────────────────
    op.create_check_constraint(
        "ck_inventory_lots_qty", "inventory_lots", "quantity_on_hand >= 0"
    )
    op.create_check_constraint(
        "ck_inventory_lots_status",
        "inventory_lots",
        "status IN ('in_storage', 'in_production', 'shipped', 'consumed')",
    )

    # ── 11. Drop old columns ──────────────────────────────────────────────────
    op.drop_column("inventory_lots", "item_name")
    op.drop_column("inventory_lots", "category")
    op.drop_column("inventory_lots", "last_updated")

    # ── 12. Rename delivery_items.inventory_item_id → inventory_lot_id ────────
    op.alter_column("delivery_items", "inventory_item_id", new_column_name="inventory_lot_id")

    # ── 13. Create inventory_transactions table ────────────────────────────────
    op.create_table(
        "inventory_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("lot_id", sa.Integer(), sa.ForeignKey("inventory_lots.id"), nullable=False),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(50), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "transaction_type IN ('receive', 'ship', 'produce', 'consume', 'adjust', 'move', 'split')",
            name="ck_inventory_txn_type",
        ),
    )
    op.create_index("idx_inventory_txn_lot", "inventory_transactions", ["lot_id"])

    # ── 14. Seed receive transaction per existing lot ─────────────────────────
    conn.execute(sa.text("""
        INSERT INTO inventory_transactions (lot_id, transaction_type, quantity, reason)
        SELECT id, 'receive', quantity_on_hand, 'Initial backfill from pre-ledger inventory'
        FROM inventory_lots
    """))

    # ── 15. Update low_stock_alerts ────────────────────────────────────────────
    # Add product_id column
    op.add_column("low_stock_alerts", sa.Column("product_id", sa.Integer(), nullable=True))

    # Drop unique constraint on item_name
    op.drop_constraint("low_stock_alerts_material_type_key", "low_stock_alerts", type_="unique")

    # Backfill product_id from product name match
    conn.execute(sa.text("""
        UPDATE low_stock_alerts lsa
        SET product_id = p.id
        FROM products p
        WHERE lsa.item_name = p.name
    """))

    # Convert threshold: Numeric → Integer ×100
    op.alter_column(
        "low_stock_alerts",
        "threshold",
        type_=sa.Integer(),
        nullable=False,
        server_default="0",
        postgresql_using="ROUND(threshold * 100)::integer",
    )

    # Add unique constraint on product_id
    op.create_unique_constraint("uq_low_stock_alerts_product_id", "low_stock_alerts", ["product_id"])

    # Add FK for product_id
    op.create_foreign_key(
        "fk_low_stock_alerts_product_id", "low_stock_alerts", "products", ["product_id"], ["id"]
    )

    # Make item_name nullable then drop it
    op.alter_column("low_stock_alerts", "item_name", nullable=True)
    op.drop_column("low_stock_alerts", "item_name")


def downgrade():
    conn = op.get_bind()

    # Restore low_stock_alerts
    op.add_column("low_stock_alerts", sa.Column("item_name", sa.String(200), nullable=True))
    conn.execute(sa.text("""
        UPDATE low_stock_alerts lsa
        SET item_name = p.name
        FROM products p
        WHERE lsa.product_id = p.id
    """))
    op.alter_column("low_stock_alerts", "item_name", nullable=False)
    op.drop_constraint("fk_low_stock_alerts_product_id", "low_stock_alerts", type_="foreignkey")
    op.drop_constraint("uq_low_stock_alerts_product_id", "low_stock_alerts", type_="unique")
    op.create_unique_constraint("low_stock_alerts_item_name_key", "low_stock_alerts", ["item_name"])
    op.alter_column(
        "low_stock_alerts",
        "threshold",
        type_=sa.Numeric(12, 3),
        nullable=False,
        server_default=None,
        postgresql_using="threshold::numeric / 100",
    )
    op.drop_column("low_stock_alerts", "product_id")

    # Drop inventory_transactions
    op.drop_index("idx_inventory_txn_lot", "inventory_transactions")
    op.drop_table("inventory_transactions")

    # Restore delivery_items column name
    op.alter_column("delivery_items", "inventory_lot_id", new_column_name="inventory_item_id")

    # Restore inventory_lots columns
    op.add_column("inventory_lots", sa.Column("item_name", sa.String(200), nullable=True))
    op.add_column("inventory_lots", sa.Column("category", sa.String(20), nullable=True))
    op.add_column(
        "inventory_lots",
        sa.Column(
            "last_updated",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            server_default=sa.text("NOW()"),
        ),
    )

    # Backfill item_name and category from products
    conn.execute(sa.text("""
        UPDATE inventory_lots il
        SET item_name = p.name, category = p.category
        FROM products p
        WHERE il.product_id = p.id
    """))
    conn.execute(sa.text("UPDATE inventory_lots SET item_name = 'unknown' WHERE item_name IS NULL"))
    conn.execute(sa.text("UPDATE inventory_lots SET category = 'raw' WHERE category IS NULL"))
    conn.execute(sa.text("UPDATE inventory_lots SET last_updated = NOW() WHERE last_updated IS NULL"))
    op.alter_column("inventory_lots", "item_name", nullable=False)
    op.alter_column("inventory_lots", "category", nullable=False)
    op.alter_column("inventory_lots", "last_updated", nullable=False)

    # Convert quantity_on_hand back to Numeric
    op.alter_column(
        "inventory_lots",
        "quantity_on_hand",
        type_=sa.Numeric(12, 3),
        nullable=False,
        server_default="0",
        postgresql_using="quantity_on_hand::numeric / 100",
    )

    # Rename lot_number back
    op.alter_column("inventory_lots", "lot_number", new_column_name="lot_batch_number")

    # Drop FK and new columns
    op.drop_constraint("fk_inventory_lots_product_id", "inventory_lots", type_="foreignkey")
    op.drop_constraint("ck_inventory_lots_qty", "inventory_lots", type_="check")
    op.drop_constraint("ck_inventory_lots_status", "inventory_lots", type_="check")
    op.drop_column("inventory_lots", "pallet_number")
    op.drop_column("inventory_lots", "status")
    op.drop_column("inventory_lots", "product_id")

    # Re-add old check constraints
    op.create_check_constraint(
        "ck_inventory_items_category", "inventory_lots", "category IN ('raw', 'finished')"
    )
    op.create_check_constraint(
        "ck_inventory_items_qty", "inventory_lots", "quantity_on_hand >= 0"
    )

    # Rename back
    op.rename_table("inventory_lots", "inventory_items")
