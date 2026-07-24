import logging
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.audit import write_audit
from app.models.contact import Contact
from app.models.delivery import Delivery, DeliveryItem
from app.models.user import User
from app.models.inventory import InventoryLot, InventoryTransaction
from app.models.product import Product
from app.schemas.auth import TokenUser
from app.schemas.delivery import (
    DeliveryCreate,
    DeliveryItemResponse,
    DeliveryListResponse,
    DeliveryResponse,
)

logger = logging.getLogger("acra.delivery")

_TRANSFER_KEYWORDS = ("transfer", "transferencia")


def _is_transfer(name: str) -> bool:
    return any(kw in name.lower() for kw in _TRANSFER_KEYWORDS)


def _apply_filters(query, supplier, carrier, bol_reference, date_from, date_to):
    if supplier:
        sc = aliased(Contact)
        query = query.join(sc, Delivery.contact_id == sc.id).where(
            sc.name.ilike(f"%{supplier}%")
        )
    if carrier:
        cc = aliased(Contact)
        query = query.join(cc, Delivery.carrier_id == cc.id).where(
            cc.name.ilike(f"%{carrier}%")
        )
    if bol_reference:
        query = query.where(Delivery.bol_reference.ilike(f"%{bol_reference}%"))
    if date_from:
        query = query.where(Delivery.delivery_date >= date_from)
    if date_to:
        query = query.where(Delivery.delivery_date <= date_to)
    return query


async def create_delivery(
    body: DeliveryCreate,
    current_user: TokenUser,
    db: AsyncSession,
) -> DeliveryResponse:
    existing = (
        await db.execute(select(Delivery).where(Delivery.bol_reference == body.bol_reference))
    ).scalar_one_or_none()
    if existing:
        if not body.force:
            logger.warning("Duplicate BOL rejected — bol=%r existing_id=%s", body.bol_reference, existing.id)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Delivery with BOL reference '{body.bol_reference}' already exists. Use force=true to override.",
            )
    contact_id = body.contact_id
    if body.carrier_id:
        carrier_contact = (
            await db.execute(select(Contact).where(Contact.id == body.carrier_id))
        ).scalar_one_or_none()
        if carrier_contact and _is_transfer(carrier_contact.name):
            internal = (
                await db.execute(
                    select(Contact).where(
                        Contact.name == "Internal", Contact.type == "provider"
                    )
                )
            ).scalar_one_or_none()
            if not internal:
                internal = Contact(name="Internal", type="provider")
                db.add(internal)
                await db.flush()
            contact_id = internal.id

    product_ids = [item.product_id for item in body.items]
    products_res = await db.execute(select(Product).where(Product.id.in_(product_ids)))
    products_by_id = {p.id: p for p in products_res.scalars().all()}

    delivery = Delivery(
        contact_id=contact_id,
        carrier_id=body.carrier_id,
        delivery_date=body.delivery_date,
        bol_reference=body.bol_reference,
        notes=body.notes,
        created_by=current_user.user_id,
    )
    db.add(delivery)
    await db.flush()

    leftover_notes: list[str] = []
    pairs: list[tuple[DeliveryItem, InventoryLot, Product]] = []

    for item_data in body.items:
        product = products_by_id.get(item_data.product_id)
        if not product:
            logger.error("Product not found — product_id=%s", item_data.product_id)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {item_data.product_id} not found",
            )

        leftover: Optional[int] = None
        if item_data.pallets is not None and item_data.units_per_pallet is not None:
            total_units_x100 = item_data.pallets * item_data.units_per_pallet * 100
            diff = total_units_x100 - item_data.quantity
            if diff != 0:
                leftover = diff
                leftover_notes.append(
                    f"{product.name}: leftover {diff / 100:+.2f} "
                    f"({item_data.pallets}p × {item_data.units_per_pallet}u/p = "
                    f"{total_units_x100 / 100} vs qty {item_data.quantity / 100})"
                )

        item = DeliveryItem(
            delivery_id=delivery.id,
            product_id=item_data.product_id,
            description=item_data.description,
            quantity=item_data.quantity,
            pallets=item_data.pallets,
            units_per_pallet=item_data.units_per_pallet,
            leftover=leftover,
        )
        db.add(item)

        lot = InventoryLot(
            product_id=item_data.product_id,
            quantity_on_hand=item_data.quantity,
            status="in_storage",
            source_delivery_item_id=None,
        )
        db.add(lot)
        pairs.append((item, lot, product))

    if leftover_notes:
        combined = "\n".join(leftover_notes)
        delivery.notes = f"{delivery.notes}\n{combined}" if delivery.notes else combined

    await db.flush()

    for item, lot, _ in pairs:
        lot.source_delivery_item_id = item.id
        item.inventory_lot_id = lot.id
        db.add(InventoryTransaction(
            lot_id=lot.id,
            transaction_type="receive",
            quantity=item.quantity,
            reference_type="delivery",
            reference_id=delivery.id,
            reason=f"Received via delivery {delivery.bol_reference}",
            created_by=current_user.user_id,
        ))

    await write_audit(
        db=db,
        user_id=current_user.user_id,
        action="delivery.created",
        entity_type="delivery",
        entity_id=delivery.id,
        details={"bol_reference": body.bol_reference, "item_count": len(body.items)},
    )
    await db.commit()

    contact_ids_to_load = {cid for cid in (contact_id, body.carrier_id) if cid}
    contacts_map: dict[int, str] = {}
    if contact_ids_to_load:
        res = await db.execute(select(Contact).where(Contact.id.in_(contact_ids_to_load)))
        contacts_map = {c.id: c.name for c in res.scalars().all()}
    contact_name = contacts_map.get(contact_id) if contact_id else None
    carrier_name = contacts_map.get(body.carrier_id) if body.carrier_id else None

    return DeliveryResponse(
        id=delivery.id,
        contact_id=contact_id,
        contact_name=contact_name,
        carrier_id=body.carrier_id,
        carrier_name=carrier_name,
        delivery_date=delivery.delivery_date,
        bol_reference=delivery.bol_reference,
        notes=delivery.notes,
        created_by=delivery.created_by,
        created_by_name=current_user.full_name,
        created_at=delivery.created_at,
        items=[
            DeliveryItemResponse(
                id=item.id,
                product_id=item.product_id,
                product_name=product.name,
                description=item.description,
                quantity=item.quantity,
                pallets=item.pallets,
                units_per_pallet=item.units_per_pallet,
                leftover=item.leftover,
                inventory_lot_id=item.inventory_lot_id,
            )
            for item, _, product in pairs
        ],
    )


async def list_deliveries(
    db: AsyncSession,
    supplier: Optional[str] = None,
    carrier: Optional[str] = None,
    bol_reference: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> DeliveryListResponse:
    base = select(Delivery)
    base = _apply_filters(base, supplier, carrier, bol_reference, date_from, date_to)

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0

    offset = (page - 1) * page_size
    rows = (
        await db.execute(
            base.order_by(Delivery.created_at.desc()).offset(offset).limit(page_size)
        )
    ).scalars().all()

    results: list[DeliveryResponse] = []
    if rows:
        items_rows = (
            await db.execute(
                select(DeliveryItem).where(DeliveryItem.delivery_id.in_([d.id for d in rows]))
            )
        ).scalars().all()

        items_map: dict[int, list[DeliveryItem]] = {}
        for it in items_rows:
            items_map.setdefault(it.delivery_id, []).append(it)

        contact_ids: set[int] = {
            cid
            for d in rows
            for cid in (d.contact_id, d.carrier_id)
            if cid
        }
        contacts_by_id: dict[int, Contact] = {}
        if contact_ids:
            contacts_res = await db.execute(
                select(Contact).where(Contact.id.in_(contact_ids))
            )
            contacts_by_id = {c.id: c for c in contacts_res.scalars().all()}

        item_product_ids: set[int] = {it.product_id for it in items_rows if it.product_id}
        products_by_id: dict[int, Product] = {}
        if item_product_ids:
            products_res = await db.execute(
                select(Product).where(Product.id.in_(item_product_ids))
            )
            products_by_id = {p.id: p for p in products_res.scalars().all()}

        creator_ids: set[int] = {d.created_by for d in rows}
        creators_by_id: dict[int, User] = {}
        if creator_ids:
            creators_res = await db.execute(select(User).where(User.id.in_(creator_ids)))
            creators_by_id = {u.id: u for u in creators_res.scalars().all()}

        for d in rows:
            contact_obj = contacts_by_id.get(d.contact_id) if d.contact_id else None
            carrier_obj = contacts_by_id.get(d.carrier_id) if d.carrier_id else None
            d_items = items_map.get(d.id, [])
            results.append(
                DeliveryResponse(
                    id=d.id,
                    contact_id=d.contact_id,
                    contact_name=contact_obj.name if contact_obj else None,
                    carrier_id=d.carrier_id,
                    carrier_name=carrier_obj.name if carrier_obj else None,
                    delivery_date=d.delivery_date,
                    bol_reference=d.bol_reference,
                    notes=d.notes,
                    created_by=d.created_by,
                    created_by_name=(
                        creators_by_id[d.created_by].full_name
                        if d.created_by in creators_by_id
                        else None
                    ),
                    created_at=d.created_at,
                    items=[
                        DeliveryItemResponse(
                            id=it.id,
                            product_id=it.product_id,
                            product_name=(
                                products_by_id[it.product_id].name
                                if it.product_id and it.product_id in products_by_id
                                else None
                            ),
                            description=it.description,
                            quantity=it.quantity,
                            pallets=it.pallets,
                            units_per_pallet=it.units_per_pallet,
                            leftover=it.leftover,
                            inventory_lot_id=it.inventory_lot_id,
                        )
                        for it in d_items
                    ],
                )
            )

    return DeliveryListResponse(total=total, page=page, page_size=page_size, results=results)
