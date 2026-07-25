"""Invoice raised against a shipment (ACR-33, carried forward from ACR-24).

One invoice per shipment, enforced by the unique FK. Amounts are ``Integer ×100`` like every other
quantity in the ledger, so totals are exact integer arithmetic with no decimal drift.

Prices come from the ``ShipmentItem.unit_price`` snapshot taken when the shipment was created —
``products`` has no price column, and an invoice must record what was charged then, not what the
catalogue says now.
"""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base

INVOICE_STATUS_ISSUED = "issued"
INVOICE_STATUS_VOID = "void"


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    shipment_id = Column(
        Integer,
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    invoice_number = Column(String(50), nullable=False, unique=True)
    invoice_date = Column(String(20), nullable=False)
    currency = Column(String(3), nullable=False, server_default="USD")
    subtotal_amount = Column(Integer, nullable=False)   # ×100
    tax_amount = Column(Integer, nullable=False, server_default="0")   # ×100
    total_amount = Column(Integer, nullable=False)      # ×100
    status = Column(String(20), nullable=False, server_default=INVOICE_STATUS_ISSUED)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('issued', 'void')", name="ck_invoices_status"),
        CheckConstraint("subtotal_amount >= 0", name="ck_invoices_subtotal"),
        CheckConstraint("tax_amount >= 0", name="ck_invoices_tax"),
        CheckConstraint("total_amount >= 0", name="ck_invoices_total"),
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(
        Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    shipment_item_id = Column(
        Integer, ForeignKey("shipment_items.id", ondelete="CASCADE"), nullable=False
    )
    description = Column(String(300), nullable=False)
    quantity = Column(Integer, nullable=False)    # ×100
    unit_price = Column(Integer, nullable=False)  # ×100
    line_total = Column(Integer, nullable=False)  # ×100

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_invoice_lines_qty"),
        CheckConstraint("unit_price >= 0", name="ck_invoice_lines_unit_price"),
        CheckConstraint("line_total >= 0", name="ck_invoice_lines_total"),
    )
