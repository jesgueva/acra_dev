from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Numeric, String, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_name = Column(String(200), nullable=False)
    category = Column(String(20), nullable=False)
    quantity_on_hand = Column(Numeric(12, 3), nullable=False, server_default="0")
    lot_batch_number = Column(String(100), nullable=True)
    storage_location = Column(String(100), nullable=True)
    source_delivery_item_id = Column(
        Integer,
        ForeignKey("delivery_items.id", use_alter=True, name="fk_inventory_items_source_delivery"),
        nullable=True,
    )
    last_updated = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("category IN ('raw', 'finished')", name="ck_inventory_items_category"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_inventory_items_qty"),
    )


class LowStockAlert(Base):
    __tablename__ = "low_stock_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_name = Column(String(200), nullable=False, unique=True)
    threshold = Column(Numeric(12, 3), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)

    __table_args__ = (
        CheckConstraint("threshold >= 0", name="ck_low_stock_alerts_threshold"),
    )
