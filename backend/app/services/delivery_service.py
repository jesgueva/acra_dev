from datetime import date
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.models.delivery import Delivery, DeliveryItem
from app.models.inventory import InventoryItem
from app.schemas.auth import TokenUser
from app.schemas.delivery import (
    DeliveryCreate,
    DeliveryItemResponse,
    DeliveryListResponse,
    DeliveryResponse,
)


def _apply_filters(query, supplier, carrier, bol_reference, date_from, date_to):
    if supplier:
        query = query.where(Delivery.supplier.ilike(f"%{supplier}%"))
    if carrier:
        query = query.where(Delivery.carrier.ilike(f"%{carrier}%"))
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
    if existing and not body.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Delivery with BOL reference '{body.bol_reference}' already exists. Use force=true to override.",
        )

    delivery = Delivery(
        supplier=body.supplier,
        carrier=body.carrier,
        delivery_date=body.delivery_date,
        bol_reference=body.bol_reference,
        created_by=current_user.user_id,
    )
    db.add(delivery)
    await db.flush()  # DB assigns delivery.id before items reference it

    delivery_items: list[DeliveryItem] = []
    for item_data in body.items:
        item = DeliveryItem(
            delivery_id=delivery.id,
            material_type=item_data.material_type,
            quantity=item_data.quantity,
            lot_batch_number=item_data.lot_batch_number,
            storage_location=item_data.storage_location,
        )
        db.add(item)
        delivery_items.append(item)
    await db.flush()  # DB assigns item IDs before inventory rows reference them

    # Build (item, inv) pairs so the link-back loop is explicit and order-safe
    pairs: list[tuple[DeliveryItem, InventoryItem]] = []
    for item in delivery_items:
        inv = InventoryItem(
            material_type=item.material_type,
            category="raw",
            quantity_on_hand=item.quantity,
            lot_batch_number=item.lot_batch_number,
            storage_location=item.storage_location,
            source_delivery_item_id=item.id,
        )
        db.add(inv)
        pairs.append((item, inv))
    await db.flush()  # DB assigns inventory IDs before we write them back

    for item, inv in pairs:
        item.inventory_item_id = inv.id

    await write_audit(
        db=db,
        user_id=current_user.user_id,
        action="delivery.created",
        entity_type="delivery",
        entity_id=delivery.id,
        details={"bol_reference": body.bol_reference, "item_count": len(body.items)},
    )
    await db.commit()

    return DeliveryResponse(
        id=delivery.id,
        supplier=delivery.supplier,
        carrier=delivery.carrier,
        delivery_date=delivery.delivery_date,
        bol_reference=delivery.bol_reference,
        created_by=delivery.created_by,
        created_at=delivery.created_at,
        items=[
            DeliveryItemResponse(
                id=item.id,
                material_type=item.material_type,
                quantity=item.quantity,
                lot_batch_number=item.lot_batch_number,
                storage_location=item.storage_location,
                inventory_item_id=item.inventory_item_id,
            )
            for item, _ in pairs
        ],
    )


async def list_deliveries(
    db: AsyncSession,
    supplier: Optional[str] = None,
    carrier: Optional[str] = None,
    bol_reference: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
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

        for d in rows:
            results.append(
                DeliveryResponse(
                    id=d.id,
                    supplier=d.supplier,
                    carrier=d.carrier,
                    delivery_date=d.delivery_date,
                    bol_reference=d.bol_reference,
                    created_by=d.created_by,
                    created_at=d.created_at,
                    items=[
                        DeliveryItemResponse.model_validate(it)
                        for it in items_map.get(d.id, [])
                    ],
                )
            )

    return DeliveryListResponse(total=total, page=page, page_size=page_size, results=results)
