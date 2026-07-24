"""Invoice generation against a shipment (ACR-33).

One invoice per shipment. Amounts stay ``Integer ×100`` end to end: ``quantity`` and ``unit_price``
are both ×100, so their product is ×10000 and is divided once to land back on ×100. Integer
division truncates deterministically — no float ever touches a money value.
"""

from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.models.contact import Contact
from app.models.inventory import InventoryLot
from app.models.invoice import INVOICE_STATUS_ISSUED, Invoice, InvoiceLine
from app.models.product import Product
from app.models.shipment import Shipment, ShipmentItem
from app.schemas.auth import TokenUser
from app.schemas.invoice import InvoiceLineResponse, InvoiceResponse

# No tax model exists anywhere in the domain docs (ACR-33 D4). The column is carried so the shape
# is right when one does; until then every invoice is untaxed.
_TAX_AMOUNT = 0


def _line_total(quantity: int, unit_price: int) -> int:
    """Both operands are ×100, so the product is ×10000 — divide once to return to ×100."""
    return (quantity * unit_price) // 100


def _invoice_number(shipment: Shipment) -> str:
    """Deterministic from the shipment, so there is no sequence for concurrent callers to race on.

    ``shipment_date`` is a ``YYYY-MM-DD`` string; anything unparseable falls back to ``0000`` rather
    than failing invoice generation over a cosmetic field.
    """
    year = (shipment.shipment_date or "")[:4]
    if not year.isdigit():
        year = "0000"
    return f"INV-{year}-{shipment.id:05d}"


def _line_response(line: InvoiceLine) -> InvoiceLineResponse:
    return InvoiceLineResponse(
        id=line.id,
        invoice_id=line.invoice_id,
        shipment_item_id=line.shipment_item_id,
        description=line.description,
        quantity=line.quantity,
        unit_price=line.unit_price,
        line_total=line.line_total,
    )


def _invoice_response(
    invoice: Invoice,
    lines: list[InvoiceLine],
    shipment: Optional[Shipment] = None,
    contact: Optional[Contact] = None,
) -> InvoiceResponse:
    return InvoiceResponse(
        id=invoice.id,
        shipment_id=invoice.shipment_id,
        invoice_number=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        currency=invoice.currency,
        subtotal_amount=invoice.subtotal_amount,
        tax_amount=invoice.tax_amount,
        total_amount=invoice.total_amount,
        status=invoice.status,
        created_by=invoice.created_by,
        created_at=invoice.created_at,
        bol_number=shipment.bol_number if shipment else None,
        contact_name=contact.name if contact else None,
        lines=[_line_response(line) for line in lines],
    )


async def _get_shipment_or_404(db: AsyncSession, shipment_id: int) -> Shipment:
    shipment = (
        await db.execute(select(Shipment).where(Shipment.id == shipment_id))
    ).scalar_one_or_none()
    if not shipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment_id} not found",
        )
    return shipment


async def _load_contact(db: AsyncSession, contact_id: Optional[int]) -> Optional[Contact]:
    if not contact_id:
        return None
    return (
        await db.execute(select(Contact).where(Contact.id == contact_id))
    ).scalar_one_or_none()


async def _describe_items(
    db: AsyncSession, items: list[ShipmentItem]
) -> dict[int, str]:
    """Map shipment_item.id → a human line description, via lot → product."""
    lot_ids = {it.lot_id for it in items}
    lots_by_id: dict[int, InventoryLot] = {}
    if lot_ids:
        rows = (
            await db.execute(select(InventoryLot).where(InventoryLot.id.in_(lot_ids)))
        ).scalars().all()
        lots_by_id = {lot.id: lot for lot in rows}

    product_ids = {lot.product_id for lot in lots_by_id.values() if lot.product_id}
    products_by_id: dict[int, Product] = {}
    if product_ids:
        rows = (
            await db.execute(select(Product).where(Product.id.in_(product_ids)))
        ).scalars().all()
        products_by_id = {p.id: p for p in rows}

    descriptions: dict[int, str] = {}
    for item in items:
        lot = lots_by_id.get(item.lot_id)
        product = products_by_id.get(lot.product_id) if lot and lot.product_id else None
        if product and lot:
            descriptions[item.id] = f"{product.name} (lot {lot.lot_number})"
        elif lot:
            descriptions[item.id] = f"Lot {lot.lot_number}"
        else:
            descriptions[item.id] = f"Lot #{item.lot_id}"
    return descriptions


async def generate_invoice(
    shipment_id: int,
    current_user: TokenUser,
    db: AsyncSession,
) -> InvoiceResponse:
    """Raise the invoice for a shipment. Invoices are immutable — a second call is a 409."""
    shipment = await _get_shipment_or_404(db, shipment_id)

    existing = (
        await db.execute(select(Invoice).where(Invoice.shipment_id == shipment_id))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Shipment {shipment_id} already has invoice {existing.invoice_number}",
        )

    items = (
        await db.execute(
            select(ShipmentItem).where(ShipmentItem.shipment_id == shipment_id)
        )
    ).scalars().all()
    if not items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Shipment {shipment_id} has no items to invoice",
        )

    descriptions = await _describe_items(db, list(items))

    invoice = Invoice(
        shipment_id=shipment.id,
        invoice_number=_invoice_number(shipment),
        invoice_date=shipment.shipment_date,
        currency="USD",
        subtotal_amount=0,
        tax_amount=_TAX_AMOUNT,
        total_amount=0,
        status=INVOICE_STATUS_ISSUED,
        created_by=current_user.user_id,
    )
    db.add(invoice)
    await db.flush()

    subtotal = 0
    lines: list[InvoiceLine] = []
    for item in items:
        # An unpriced line still belongs on the invoice — it just contributes nothing.
        unit_price = item.unit_price or 0
        line_total = _line_total(item.quantity, unit_price)
        subtotal += line_total

        line = InvoiceLine(
            invoice_id=invoice.id,
            shipment_item_id=item.id,
            description=descriptions.get(item.id, f"Lot #{item.lot_id}"),
            quantity=item.quantity,
            unit_price=unit_price,
            line_total=line_total,
        )
        db.add(line)
        lines.append(line)

    invoice.subtotal_amount = subtotal
    invoice.total_amount = subtotal + _TAX_AMOUNT

    await db.flush()

    await write_audit(
        db=db,
        user_id=current_user.user_id,
        action="invoice.created",
        entity_type="invoice",
        entity_id=invoice.id,
        details={
            "invoice_number": invoice.invoice_number,
            "shipment_id": shipment.id,
            "total_amount": invoice.total_amount,
        },
    )
    await db.commit()

    contact = await _load_contact(db, shipment.contact_id)
    return _invoice_response(invoice, lines, shipment, contact)


async def get_invoice_for_shipment(
    shipment_id: int,
    db: AsyncSession,
) -> InvoiceResponse:
    shipment = await _get_shipment_or_404(db, shipment_id)

    invoice = (
        await db.execute(select(Invoice).where(Invoice.shipment_id == shipment_id))
    ).scalar_one_or_none()
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment_id} has no invoice",
        )

    lines = (
        await db.execute(
            select(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id)
        )
    ).scalars().all()

    contact = await _load_contact(db, shipment.contact_id)
    return _invoice_response(invoice, list(lines), shipment, contact)
