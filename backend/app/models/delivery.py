from sqlalchemy import Column, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    carrier_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    delivery_date = Column(String(20), nullable=False)
    bol_reference = Column(String(100), nullable=False)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class DeliveryItem(Base):
    __tablename__ = "delivery_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    delivery_id = Column(Integer, ForeignKey("deliveries.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    description = Column(Text, nullable=True)
    quantity = Column(Integer, nullable=False)          # ×100
    pallets = Column(Integer, nullable=True)
    units_per_pallet = Column(Integer, nullable=True)
    leftover = Column(Integer, nullable=True)           # ×100
    inventory_lot_id = Column(Integer, ForeignKey("inventory_lots.id"), nullable=True)
