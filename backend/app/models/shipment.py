from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)   # client
    carrier_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    bol_number = Column(String(100), nullable=False)
    shipment_date = Column(String(20), nullable=False)
    notes = Column(Text, nullable=True)
    type = Column(String(30), nullable=False, server_default="customer_order")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "type IN ('customer_order', 'transfer_out')",
            name="ck_shipments_type",
        ),
    )


class ShipmentItem(Base):
    __tablename__ = "shipment_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    shipment_id = Column(
        Integer, ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False
    )
    lot_id = Column(
        Integer,
        ForeignKey("inventory_lots.id", use_alter=True, name="fk_shipment_items_lot_id"),
        nullable=False,
    )
    quantity = Column(Integer, nullable=False)  # ×100
