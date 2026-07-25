"""Stock reservations — the "reserved / available" layer over the inventory ledger.

A reservation earmarks a quantity of an item for an open Production Worksheet: it reduces what new
worksheets can draw on (``available``) **without** touching ``on_hand``. Stock only leaves the
warehouse at worksheet close (ACR-31), which is where the movement is written — so a reservation
deliberately records no stock movement of its own.

``product_id`` is the "item" and ``state`` reuses :class:`app.models.inventory.LotStatus` — the
lifecycle vocabulary the ``inventory_lots.status`` constraint already stores, not the Phase 2
``StockState``, which describes a ledger that does not exist yet.
"""

from enum import Enum

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class ReservationStatus(str, Enum):
    """Lifecycle of a reservation."""

    ACTIVE = "active"
    RELEASED = "released"


class StockReservation(Base):
    __tablename__ = "stock_reservations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)  # the "item"
    state = Column(String(20), nullable=False, server_default="in_storage")
    quantity = Column(Integer, nullable=False)  # ×100, always > 0
    # Forward reference to ACR-29's production_worksheet_lines — the FK lands with that table.
    production_worksheet_line_id = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, server_default="active")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    released_at = Column(TIMESTAMP(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_reservations_qty"),
        CheckConstraint("status IN ('active', 'released')", name="ck_stock_reservations_status"),
        CheckConstraint(
            "state IN ('in_storage', 'in_production', 'shipped', 'consumed')",
            name="ck_stock_reservations_state",
        ),
        # RSK-04 — covers the `product_id = ? AND state = ? AND status = 'active'` aggregation.
        Index("ix_stock_reservations_item_state", "product_id", "state", "status"),
    )
