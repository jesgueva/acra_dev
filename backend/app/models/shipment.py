from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base

# Domain model §4.3 — the two outbound delivery-note flavors.
SHIPMENT_TYPE_TRANSFER = "transfer"
SHIPMENT_TYPE_DIRECT_CUSTOMER = "direct_customer"


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)   # client
    carrier_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    bol_number = Column(String(100), nullable=False)
    shipment_date = Column(String(20), nullable=False)
    notes = Column(Text, nullable=True)
    type = Column(String(30), nullable=False, server_default=SHIPMENT_TYPE_DIRECT_CUSTOMER)
    # §4.3 — originating stock location on a Direct Customer note, e.g. "SC".
    source = Column(String(50), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "type IN ('transfer', 'direct_customer')",
            name="ck_shipments_type",
        ),
        CheckConstraint(
            "source IS NULL OR type = 'direct_customer'",
            name="ck_shipments_source_direct_only",
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
    # Price snapshot taken at ship time — `products` carries no price. ×100.
    unit_price = Column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "unit_price IS NULL OR unit_price >= 0",
            name="ck_shipment_items_unit_price",
        ),
    )
