from sqlalchemy import CheckConstraint, Column, Date, ForeignKey, Integer, Numeric, String, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier = Column(String(200), nullable=False)
    carrier = Column(String(200), nullable=False)
    delivery_date = Column(Date, nullable=False)
    bol_reference = Column(String(100), nullable=False, unique=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class DeliveryItem(Base):
    __tablename__ = "delivery_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False)
    material_type = Column(String(200), nullable=False)
    quantity = Column(Numeric(12, 3), nullable=False)
    lot_batch_number = Column(String(100), nullable=False)
    storage_location = Column(String(100), nullable=False)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_delivery_items_quantity"),
    )
