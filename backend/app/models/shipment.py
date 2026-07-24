from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, Text, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class Shipment(Base):
    """Outbound shipment header.

    The document facts — client, BoL number, date, and the transfer/direct-customer flavour — live
    on the linked :class:`~app.models.delivery_note.DeliveryNote`, not here. This row keeps only
    what is specific to shipping: the carrier and the lot-level line items.
    """

    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    delivery_note_id = Column(
        Integer, ForeignKey("delivery_notes.id"), nullable=False, unique=True
    )
    carrier_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


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
