"""inventory_lots aggregation index — the measured half of RSK-04's mitigation (A8-6)

RSK-04's stated mitigation is *"index by ``(item, state)``"*. It was only ever half-applied:
``stock_reservations`` got ``ix_stock_reservations_item_state`` in revision 010, while
``inventory_lots`` carried no index at all beyond its primary key. So on every
``reservation_service.availability`` call the ``_reserved`` half was indexed and the ``_on_hand``
half sequentially scanned the whole table.

This revision closes that asymmetry, and unlike the 010 index it is landing with a measurement
behind it (ACR-45, ``validation-evidence/aggregation-bench-summary.json``). Server-side execution
time for the ``_on_hand`` aggregate, real service calls against a seeded database:

===========  ==============  ============  =========
bench lots   without index   with index    plan
===========  ==============  ============  =========
1 000        2.688 ms        0.036 ms      Seq Scan -> Index Only Scan
10 000       3.365 ms        0.024 ms      Seq Scan -> Index Only Scan
===========  ==============  ============  =========

``INCLUDE (quantity_on_hand)`` is what makes those *index-only* scans: the aggregate sums that
column, so carrying it in the index leaf means the query never touches the heap. The narrower
``(product_id, status)`` index still helps, but leaves a heap fetch per matching row.

**Scope, deliberately.** This index serves the point-lookup aggregate only. It does **not** help
``inventory_service.list_alerts``, which groups over the entire table with no ``WHERE`` clause and
measured unchanged at ~5 ms either way — that path stays a sequential scan and A8-6 reports it as
such rather than claiming a win the numbers do not support.

Revision ID: 015
Revises: 014
Create Date: 2026-07-31
"""
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_inventory_lots_item_state"


def upgrade():
    # RSK-04 — the on-hand aggregation filters on exactly these two columns and sums the third.
    op.create_index(
        INDEX_NAME,
        "inventory_lots",
        ["product_id", "status"],
        postgresql_include=["quantity_on_hand"],
    )


def downgrade():
    op.drop_index(INDEX_NAME, table_name="inventory_lots")
