"""delivery fk refactor

Revision ID: 006
Revises: 005
Create Date: 2026-04-09
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add new FK columns (nullable for backfill)
    op.add_column("deliveries", sa.Column("contact_id", sa.Integer(), nullable=True))
    op.add_column("deliveries", sa.Column("carrier_id", sa.Integer(), nullable=True))
    op.add_column("delivery_items", sa.Column("product_id", sa.Integer(), nullable=True))

    # 2. Backfill contacts from unique supplier strings
    conn = op.get_bind()
    suppliers = conn.execute(
        sa.text("SELECT DISTINCT supplier FROM deliveries WHERE supplier IS NOT NULL")
    ).fetchall()
    for (sup,) in suppliers:
        result = conn.execute(
            sa.text("INSERT INTO contacts (name, type) VALUES (:name, 'provider') RETURNING id"),
            {"name": sup},
        )
        contact_id = result.fetchone()[0]
        conn.execute(
            sa.text("UPDATE deliveries SET contact_id = :cid WHERE supplier = :sup"),
            {"cid": contact_id, "sup": sup},
        )

    # 3. Backfill carrier contacts from unique carrier strings
    carriers = conn.execute(
        sa.text("SELECT DISTINCT carrier FROM deliveries WHERE carrier IS NOT NULL")
    ).fetchall()
    for (car,) in carriers:
        result = conn.execute(
            sa.text("INSERT INTO contacts (name, type) VALUES (:name, 'carrier') RETURNING id"),
            {"name": car},
        )
        carrier_id = result.fetchone()[0]
        conn.execute(
            sa.text("UPDATE deliveries SET carrier_id = :cid WHERE carrier = :car"),
            {"cid": carrier_id, "car": car},
        )

    # 4. Backfill products from unique item_name strings
    items = conn.execute(
        sa.text("SELECT DISTINCT item_name FROM delivery_items WHERE item_name IS NOT NULL")
    ).fetchall()
    for (name,) in items:
        result = conn.execute(
            sa.text("INSERT INTO products (name, category) VALUES (:name, 'raw') RETURNING id"),
            {"name": name},
        )
        product_id = result.fetchone()[0]
        conn.execute(
            sa.text("UPDATE delivery_items SET product_id = :pid WHERE item_name = :name"),
            {"pid": product_id, "name": name},
        )

    # 5. Convert quantity and leftover from Numeric to Integer (×100)
    conn.execute(sa.text("UPDATE delivery_items SET quantity = ROUND(quantity * 100)::integer"))
    conn.execute(
        sa.text(
            "UPDATE delivery_items SET leftover = ROUND(leftover * 100)::integer WHERE leftover IS NOT NULL"
        )
    )

    # 6. Alter quantity and leftover columns to Integer
    op.alter_column(
        "delivery_items",
        "quantity",
        type_=sa.Integer(),
        postgresql_using="ROUND(quantity)::integer",
    )
    op.alter_column(
        "delivery_items",
        "leftover",
        existing_type=sa.Numeric(12, 3),
        type_=sa.Integer(),
        nullable=True,
        postgresql_using="ROUND(leftover)::integer",
    )

    # 7. Add FK constraints now that data is backfilled
    op.create_foreign_key(
        "fk_deliveries_contact_id", "deliveries", "contacts", ["contact_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_deliveries_carrier_id", "deliveries", "contacts", ["carrier_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_delivery_items_product_id", "delivery_items", "products", ["product_id"], ["id"]
    )

    # 8. Drop old string columns
    op.drop_column("deliveries", "supplier")
    op.drop_column("deliveries", "carrier")
    op.drop_column("delivery_items", "item_name")


def downgrade():
    # Re-add string columns
    op.add_column("deliveries", sa.Column("supplier", sa.String(200), nullable=True))
    op.add_column("deliveries", sa.Column("carrier", sa.String(200), nullable=True))
    op.add_column("delivery_items", sa.Column("item_name", sa.String(200), nullable=True))

    # Backfill strings from contacts/products
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE deliveries d SET supplier = c.name "
            "FROM contacts c WHERE d.contact_id = c.id"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE deliveries d SET carrier = c.name "
            "FROM contacts c WHERE d.carrier_id = c.id"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE delivery_items di SET item_name = p.name "
            "FROM products p WHERE di.product_id = p.id"
        )
    )

    # Drop FK constraints
    op.drop_constraint("fk_deliveries_contact_id", "deliveries", type_="foreignkey")
    op.drop_constraint("fk_deliveries_carrier_id", "deliveries", type_="foreignkey")
    op.drop_constraint("fk_delivery_items_product_id", "delivery_items", type_="foreignkey")

    op.drop_column("deliveries", "contact_id")
    op.drop_column("deliveries", "carrier_id")
    op.drop_column("delivery_items", "product_id")

    op.alter_column(
        "delivery_items",
        "quantity",
        type_=sa.Numeric(12, 3),
        postgresql_using="quantity::numeric / 100",
    )
    op.alter_column(
        "delivery_items",
        "leftover",
        type_=sa.Numeric(12, 3),
        nullable=True,
        postgresql_using="leftover::numeric / 100",
    )
