"""Delivery Note — the unified document every stock movement attaches to.

Domain model §4.1 states that *every* stock movement is attached to a Delivery Note, and §4.2
splits notes into two provenances: **uploaded** (an external document that arrived with the goods)
and **system-generated** (internal issues to production, finished-good receipts, customer
shipments).

Before this model, `deliveries` (inbound) and `shipments` (outbound) each carried the same six
document facts under different column names, and nothing at all modelled the internal case. This
table owns those facts; `deliveries` and `shipments` reference it 1:1 and keep only what is
genuinely channel-specific (their carrier and their line items).
"""

from enum import Enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    Text,
    TIMESTAMP,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base


class DeliveryNoteType(str, Enum):
    """The four document kinds of §4.1/§4.3."""

    INBOUND = "inbound"                    # goods arriving from a supplier or client return
    TRANSFER = "transfer"                  # out to a transfer partner (e.g. San Cayetano)
    DIRECT_CUSTOMER = "direct_customer"    # out to the end customer; carries `source`
    INTERNAL = "internal"                  # system-generated: production issues and FG receipts


#: Values allowed in the DB CHECK constraint, in enum order.
DELIVERY_NOTE_TYPES: tuple[str, ...] = tuple(t.value for t in DeliveryNoteType)


class DeliveryNote(Base):
    __tablename__ = "delivery_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String(20), nullable=False)
    # §4.3 — originating stock location on a Direct Customer note, e.g. "SC".
    source = Column(String(50), nullable=True)
    # NULL for INTERNAL notes: production consumes from ourselves, there is no counterparty.
    partner_id = Column(Integer, ForeignKey("contacts.id"), nullable=True)
    document_number = Column(String(100), nullable=False)
    # String(20) to match `deliveries.delivery_date` / `shipments.shipment_date`, rather than
    # introducing a third date convention. Converting all three is a separate sweep.
    document_date = Column(String(20), nullable=False)
    # §4.2 provenance: True = an external document arrived with the goods.
    uploaded = Column(Boolean, nullable=False, server_default="false")
    notes = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "type IN ('inbound', 'transfer', 'direct_customer', 'internal')",
            name="ck_delivery_notes_type",
        ),
        # §4.3 scopes `source` to the direct-customer flavour.
        CheckConstraint(
            "source IS NULL OR type = 'direct_customer'",
            name="ck_delivery_notes_source_direct_only",
        ),
        # Document numbers are the client's own convention and only unique within a kind:
        # an INBOUND BoL and an outbound BoL may legitimately share a string.
        UniqueConstraint("type", "document_number", name="uq_delivery_notes_type_document_number"),
    )
