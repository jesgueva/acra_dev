from enum import Enum

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class LotStatus(str, Enum):
    """Where a lot sits in its lifecycle — the *lifecycle* axis.

    Distinct from :class:`app.models.stock_movement.StockState`, which is the *material* axis
    (RAW_MATERIAL → WORK_IN_PROGRESS → FINISHED_GOOD). The two are orthogonal: a lot is
    ``IN_STORAGE`` *and* raw material at the same time. Conflating them was the ACR-26 defect —
    see ``acra_docs/reference/target_schema.md`` §2.

    This axis is what the lot-centric model actually stores today. It is the source of truth for
    ``InventoryLot.status`` — the column default and its check constraint are both derived from the
    members below, so the enum and the database can no longer disagree. Service-layer queries still
    compare against string literals (``allocation_service``, ``work_order_service``,
    ``shipment_service``, ``delivery_service``); migrating those to this enum is follow-up work.

    Reservations (ACR-27) key on this axis rather than re-declaring the vocabulary, and
    deliberately not on ``StockState``: that enum describes the not-yet-built Phase 2 ledger, so
    coupling reservations to it would make them churn with an unshipped redesign.

    The Sprint II ledger migration converts lot statuses and reservation states to the material axis
    **together**; until then, code that reads ``inventory_lots`` uses this enum and code that
    describes the future ledger uses ``StockState``.
    """

    IN_STORAGE = "in_storage"
    IN_PRODUCTION = "in_production"
    SHIPPED = "shipped"
    CONSUMED = "consumed"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Member values in declaration order — for defaults and check constraints."""
        return tuple(member.value for member in cls)


class InventoryLot(Base):
    __tablename__ = "inventory_lots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    lot_number = Column(String(100), nullable=True)
    storage_location = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, server_default=LotStatus.IN_STORAGE.value)
    quantity_on_hand = Column(Integer, nullable=False, server_default="0")
    source_delivery_item_id = Column(
        Integer,
        ForeignKey("delivery_items.id", use_alter=True, name="fk_inventory_lots_source_delivery"),
        nullable=True,
    )
    pallet_number = Column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ({})".format(", ".join(f"'{v}'" for v in LotStatus.values())),
            name="ck_inventory_lots_status",
        ),
        CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_lots_qty"),
    )


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lot_id = Column(Integer, ForeignKey("inventory_lots.id"), nullable=False)
    transaction_type = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False)  # ×100; positive = in, negative = out
    reference_type = Column(String(50), nullable=True)
    reference_id = Column(Integer, nullable=True)
    reason = Column(String(500), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('receive', 'ship', 'produce', 'consume', 'adjust', 'move', 'split')",
            name="ck_inventory_txn_type",
        ),
    )


# Backward-compatibility alias used by allocation/work-order services (pre-phase-3 naming)
InventoryItem = InventoryLot


class LowStockAlert(Base):
    __tablename__ = "low_stock_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, unique=True)
    threshold = Column(Integer, nullable=False)  # ×100
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        CheckConstraint("threshold >= 0", name="ck_low_stock_alerts_threshold"),
    )
