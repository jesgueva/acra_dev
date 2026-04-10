from sqlalchemy import Column, ForeignKey, Integer, Numeric, String, Text, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    supplier = Column(String(200), nullable=False)
    carrier = Column(String(200), nullable=False)
    delivery_date = Column(String(20), nullable=False)
    bol_reference = Column(String(100), nullable=False)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class DeliveryItem(Base):
    __tablename__ = "delivery_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False)
    item_name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    quantity = Column(Numeric(12, 3), nullable=False)
    pallets = Column(Integer, nullable=True)
    units_per_pallet = Column(Integer, nullable=True)
    leftover = Column(Numeric(12, 3), nullable=True)
    inventory_item_id = Column(Integer, ForeignKey("inventory_items.id"), nullable=True)
