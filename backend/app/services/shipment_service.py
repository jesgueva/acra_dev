from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.models.contact import Contact
from app.models.delivery_note import DeliveryNote
from app.models.inventory import InventoryLot, InventoryTransaction
from app.models.product import Product
from app.models.shipment import Shipment, ShipmentItem
from app.schemas.auth import TokenUser
from app.schemas.shipment import (
    ShipmentCreate,
    ShipmentItemResponse,
    ShipmentListResponse,
    ShipmentResponse,
)
from app.services import contact_service, delivery_note_service


def _item_response(
    si: ShipmentItem,
    lots_by_id: dict[int, InventoryLot],
    products_by_id: dict[int, Product],
) -> ShipmentItemResponse:
    lot = lots_by_id.get(si.lot_id)
    product_name = (
        products_by_id[lot.product_id].name
        if lot and lot.product_id and lot.product_id in products_by_id
        else None
    )
    return ShipmentItemResponse(
        id=si.id,
        shipment_id=si.shipment_id,
        lot_id=si.lot_id,
        quantity=si.quantity,
        product_name=product_name,
        lot_number=lot.lot_number if lot else None,
    )


def _shipment_response(
    s: Shipment,
    items: list[ShipmentItem],
    contacts_by_id: dict[int, Contact],
    lots_by_id: dict[int, InventoryLot],
    products_by_id: dict[int, Product],
    note: Optional[DeliveryNote] = None,
) -> ShipmentResponse:
    partner_id = note.partner_id if note else None
    contact_obj = contacts_by_id.get(partner_id) if partner_id else None
    carrier_obj = contacts_by_id.get(s.carrier_id) if s.carrier_id else None
    return ShipmentResponse(
        id=s.id,
        delivery_note_id=s.delivery_note_id,
        contact_id=partner_id,
        contact_name=contact_obj.name if contact_obj else None,
        carrier_id=s.carrier_id,
        carrier_name=carrier_obj.name if carrier_obj else None,
        bol_number=note.document_number if note else "",
        shipment_date=note.document_date if note else "",
        notes=s.notes,
        type=note.type if note else "",
        source=note.source if note else None,
        created_by=s.created_by,
        created_at=s.created_at,
        items=[_item_response(it, lots_by_id, products_by_id) for it in items],
    )


async def _load_lots(db: AsyncSession, ids: set[int]) -> dict[int, InventoryLot]:
    if not ids:
        return {}
    res = await db.execute(select(InventoryLot).where(InventoryLot.id.in_(ids)))
    return {lot.id: lot for lot in res.scalars().all()}


async def _load_products(db: AsyncSession, ids: set[int]) -> dict[int, Product]:
    if not ids:
        return {}
    res = await db.execute(select(Product).where(Product.id.in_(ids)))
    return {p.id: p for p in res.scalars().all()}


async def create_shipment(
    body: ShipmentCreate,
    current_user: TokenUser,
    db: AsyncSession,
) -> ShipmentResponse:
    lot_ids = [item.lot_id for item in body.items]
    lots_by_id = await _load_lots(db, set(lot_ids))

    for item in body.items:
        lot = lots_by_id.get(item.lot_id)
        if lot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inventory lot {item.lot_id} not found",
            )
        if lot.quantity_on_hand < item.quantity:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Insufficient stock for lot {item.lot_id}: "
                    f"requested {item.quantity / 100:.2f}, "
                    f"available {lot.quantity_on_hand / 100:.2f}"
                ),
            )

    # §4.1/§4.3 — the shipment's document is a system-generated note of the transfer or
    # direct-customer flavour, and it owns the client, BoL number, date and `source`.
    note = await delivery_note_service.add_document_note(
        db,
        note_type=body.type,
        document_number=body.bol_number,
        document_date=body.shipment_date,
        partner_id=body.contact_id,
        source=body.source,
        uploaded=False,
        created_by=current_user.user_id,
    )

    shipment = Shipment(
        delivery_note_id=note.id,
        carrier_id=body.carrier_id,
        notes=body.notes,
        created_by=current_user.user_id,
    )
    db.add(shipment)
    await db.flush()

    shipment_items: list[ShipmentItem] = []
    for item_data in body.items:
        lot = lots_by_id[item_data.lot_id]

        si = ShipmentItem(
            shipment_id=shipment.id,
            lot_id=item_data.lot_id,
            quantity=item_data.quantity,
        )
        db.add(si)

        lot.quantity_on_hand -= item_data.quantity
        if lot.quantity_on_hand == 0:
            lot.status = "shipped"

        db.add(InventoryTransaction(
            lot_id=item_data.lot_id,
            transaction_type="ship",
            quantity=-item_data.quantity,
            reference_type="shipment",
            reference_id=shipment.id,
            created_by=current_user.user_id,
        ))
        shipment_items.append(si)

    await db.flush()

    await write_audit(
        db=db,
        user_id=current_user.user_id,
        action="shipment.created",
        entity_type="shipment",
        entity_id=shipment.id,
        details={"bol_number": body.bol_number, "item_count": len(body.items)},
    )
    await db.commit()

    contact_ids: set[int] = {cid for cid in (body.contact_id, body.carrier_id) if cid}
    contacts_by_id = await contact_service.load_by_ids(db, contact_ids)
    product_ids = {lot.product_id for lot in lots_by_id.values() if lot.product_id}
    products_by_id = await _load_products(db, product_ids)

    return _shipment_response(
        shipment, shipment_items, contacts_by_id, lots_by_id, products_by_id, note
    )


async def list_shipments(
    db: AsyncSession,
    contact_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> ShipmentListResponse:
    # Client and date live on the linked note, so both filters read through the join.
    base = select(Shipment).join(
        DeliveryNote, Shipment.delivery_note_id == DeliveryNote.id
    )
    if contact_id:
        base = base.where(DeliveryNote.partner_id == contact_id)
    if date_from:
        base = base.where(DeliveryNote.document_date >= date_from)
    if date_to:
        base = base.where(DeliveryNote.document_date <= date_to)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    offset = (page - 1) * page_size
    rows = (
        await db.execute(
            base.order_by(Shipment.created_at.desc()).offset(offset).limit(page_size)
        )
    ).scalars().all()

    results: list[ShipmentResponse] = []
    if rows:
        items_rows = (
            await db.execute(
                select(ShipmentItem).where(
                    ShipmentItem.shipment_id.in_([s.id for s in rows])
                )
            )
        ).scalars().all()

        items_map: dict[int, list[ShipmentItem]] = {}
        for it in items_rows:
            items_map.setdefault(it.shipment_id, []).append(it)

        notes_by_id = await delivery_note_service.load_by_ids(db, {s.delivery_note_id for s in rows})

        contact_ids: set[int] = set()
        for s in rows:
            note = notes_by_id.get(s.delivery_note_id)
            for cid in ((note.partner_id if note else None), s.carrier_id):
                if cid:
                    contact_ids.add(cid)

        contacts_by_id = await contact_service.load_by_ids(db, contact_ids)

        lot_ids = {it.lot_id for it in items_rows}
        lots_by_id = await _load_lots(db, lot_ids)
        product_ids = {lot.product_id for lot in lots_by_id.values() if lot.product_id}
        products_by_id = await _load_products(db, product_ids)

        results = [
            _shipment_response(
                s,
                items_map.get(s.id, []),
                contacts_by_id,
                lots_by_id,
                products_by_id,
                notes_by_id.get(s.delivery_note_id),
            )
            for s in rows
        ]

    return ShipmentListResponse(total=total, page=page, page_size=page_size, results=results)


async def get_shipment(db: AsyncSession, shipment_id: int) -> ShipmentResponse:
    shipment = (
        await db.execute(select(Shipment).where(Shipment.id == shipment_id))
    ).scalar_one_or_none()
    if not shipment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Shipment {shipment_id} not found",
        )

    items_rows = (
        await db.execute(
            select(ShipmentItem).where(ShipmentItem.shipment_id == shipment_id)
        )
    ).scalars().all()

    note = (await delivery_note_service.load_by_ids(db, {shipment.delivery_note_id})).get(
        shipment.delivery_note_id
    )

    contact_ids = {
        cid
        for cid in ((note.partner_id if note else None), shipment.carrier_id)
        if cid
    }
    contacts_by_id = await contact_service.load_by_ids(db, contact_ids)

    lot_ids = {it.lot_id for it in items_rows}
    lots_by_id = await _load_lots(db, lot_ids)
    product_ids = {lot.product_id for lot in lots_by_id.values() if lot.product_id}
    products_by_id = await _load_products(db, product_ids)

    return _shipment_response(
        shipment, list(items_rows), contacts_by_id, lots_by_id, products_by_id, note
    )
