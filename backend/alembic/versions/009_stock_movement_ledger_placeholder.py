"""stock_movement ledger — placeholder (Phase 2 skeleton)

Reserves the next migration slot for the append-only StockMovement ledger (Phase 2). This
revision is intentionally a **no-op**: the concrete ``stock_movements`` table and the backfill
from the lot-centric model are designed in Sprint II (see docs/architecture.md, RISK_LOG.md
RSK-02). Having the slot in the chain keeps migration history continuous and signals the planned
schema evolution without changing the current schema.

Revision ID: 009
Revises: 008
Create Date: 2026-06-16
"""

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade():
    # No-op placeholder. The StockMovement ledger table + backfill land in Sprint II.
    pass


def downgrade():
    # No-op placeholder.
    pass
