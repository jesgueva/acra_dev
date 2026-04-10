from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class InventoryLot(Base):
    __tablename__ = "inventory_lots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    lot_number = Column(String(100), nullable=True)
    storage_location = Column(String(100), nullable=True)
    status = Column(String(20), nullable=False, server_default="in_storage")
    quantity_on_hand = Column(Integer, nullable=False, server_default="0")
    source_delivery_item_id = Column(
        Integer,
        ForeignKey("delivery_items.id", use_alter=True, name="fk_inventory_lots_source_delivery"),
        nullable=True,
    )
    pallet_number = Column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('in_storage', 'in_production', 'shipped', 'consumed')",
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
