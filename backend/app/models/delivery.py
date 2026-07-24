from sqlalchemy import Column, ForeignKey, Integer, Text, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class Delivery(Base):
    """Inbound receiving header.

    The document facts — partner, BoL reference, date — live on the linked
    :class:`~app.models.delivery_note.DeliveryNote` (type ``inbound``), not here. This row keeps
    only what is specific to receiving: the carrier and the transcribed line items.
    """

    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    delivery_note_id = Column(
        Integer, ForeignKey("delivery_notes.id"), nullable=False, unique=True
    )
    carrier_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
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
