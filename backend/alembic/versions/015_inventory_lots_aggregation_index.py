"""inventory_lots aggregation index — the measured half of RSK-04's mitigation (A8-6)

RSK-04's stated mitigation is *"index by ``(item, state)``"*. It was only ever half-applied:
``stock_reservations`` got ``ix_stock_reservations_item_state`` in revision 010, while
``inventory_lots`` carried no index at all beyond its primary key. So on every
``reservation_service.availability`` call the ``_reserved`` half was indexed and the ``_on_hand``
half sequentially scanned the whole table.

This revision closes that asymmetry, and unlike the 010 index it is landing with a measurement
behind it (ACR-45, ``validation-evidence/aggregation-bench-summary.json``). Server-side execution
time for the ``_on_hand`` aggregate, real service calls against a seeded database:

===========  ==============  ============  =============================
bench lots   without index   with index    plan
===========  ==============  ============  =============================
1 000        2.871 ms        0.034 ms      Seq Scan -> Index Only Scan
10 000       2.554 ms        0.038 ms      Seq Scan -> Index Only Scan
50 000       3.943 ms        0.009 ms      Seq Scan -> Index Only Scan
200 000      14.134 ms       0.029 ms      Seq Scan -> Index Only Scan
===========  ==============  ============  =============================

The shape matters more than any single ratio: unindexed cost grows with the table while indexed
cost stays flat and sub-0.04 ms across the whole sweep.

``INCLUDE (quantity_on_hand)`` is what makes those *index-only* scans: the aggregate sums that
column, so carrying it in the index leaf means the query never touches the heap. The narrower
``(product_id, status)`` index still helps, but leaves a heap fetch per matching row.

**Scope, deliberately.** This index serves the point-lookup aggregate only. It does **not** change
the plan for ``inventory_service.list_alerts``, which groups over the entire table with no ``WHERE``
clause: that path stays a ``Seq Scan`` at every volume measured (45.6 ms -> 29.7 ms at 200 000 lots
— the INCLUDE column shaves heap reads off the aggregate, but the scan remains sequential). A8-6
reports that rather than claiming a win the numbers do not support.

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
    #
    # Built without CONCURRENTLY on purpose. A plain CREATE INDEX takes ACCESS EXCLUSIVE for the
    # duration, which on a large `inventory_lots` blocks reads and writes — but this project applies
    # migrations as a one-shot step the API waits on before it starts serving (the `migrate` service
    # in docker-compose.yml, which `backend` gates on with `service_completed_successfully`), so
    # there is no concurrent traffic to block. CONCURRENTLY would also have to run outside a
    # transaction via `op.get_context().autocommit_block()`, giving up the transactional DDL every
    # other revision in this tree relies on, and it can leave an INVALID index behind on failure.
    # Revisit if migrations ever move to a live-traffic deploy.
    op.create_index(
        INDEX_NAME,
        "inventory_lots",
        ["product_id", "status"],
        postgresql_include=["quantity_on_hand"],
    )


def downgrade():
    op.drop_index(INDEX_NAME, table_name="inventory_lots")
