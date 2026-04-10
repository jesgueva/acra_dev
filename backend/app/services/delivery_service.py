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

_TRANSFER_KEYWORDS = ("transfer", "transferencia")


def _is_transfer(carrier: str) -> bool:
    return any(kw in carrier.lower() for kw in _TRANSFER_KEYWORDS)


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
    # Transfer-carrier rule: force supplier to Internal
    supplier = "Internal" if _is_transfer(body.carrier) else body.supplier

    existing = (
        await db.execute(select(Delivery).where(Delivery.bol_reference == body.bol_reference))
    ).scalar_one_or_none()
    if existing and not body.force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Delivery with BOL reference '{body.bol_reference}' already exists. Use force=true to override.",
        )

    delivery = Delivery(
        supplier=supplier,
        carrier=body.carrier,
        delivery_date=body.delivery_date,
        bol_reference=body.bol_reference,
        notes=body.notes,
        created_by=current_user.user_id,
    )
    db.add(delivery)
    await db.flush()

    delivery_items: list[DeliveryItem] = []
    leftover_notes: list[str] = []

    for item_data in body.items:
        leftover: Optional[float] = None
        if item_data.pallets is not None and item_data.units_per_pallet is not None:
            total_units = item_data.pallets * item_data.units_per_pallet
            diff = total_units - item_data.quantity
            if diff != 0:
                leftover = diff
                leftover_notes.append(
                    f"{item_data.item_name}: leftover {diff:+.3f} "
                    f"({item_data.pallets}p × {item_data.units_per_pallet}u/p = {total_units} vs qty {item_data.quantity})"
                )

        item = DeliveryItem(
            delivery_id=delivery.id,
            item_name=item_data.item_name,
            description=item_data.description,
            quantity=item_data.quantity,
            pallets=item_data.pallets,
            units_per_pallet=item_data.units_per_pallet,
            leftover=leftover,
        )
        db.add(item)
        delivery_items.append(item)

    await db.flush()

    # Append computed leftover notes to delivery notes
    if leftover_notes:
        combined = "\n".join(leftover_notes)
        delivery.notes = f"{delivery.notes}\n{combined}" if delivery.notes else combined

    pairs: list[tuple[DeliveryItem, InventoryItem]] = []
    for item in delivery_items:
        inv = InventoryItem(
            item_name=item.item_name,
            category="raw",
            quantity_on_hand=item.quantity,
            source_delivery_item_id=item.id,
        )
        db.add(inv)
        pairs.append((item, inv))
    await db.flush()

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
        notes=delivery.notes,
        created_by=delivery.created_by,
        created_at=delivery.created_at,
        items=[
            DeliveryItemResponse(
                id=item.id,
                item_name=item.item_name,
                description=item.description,
                quantity=float(item.quantity),
                pallets=item.pallets,
                units_per_pallet=item.units_per_pallet,
                leftover=float(item.leftover) if item.leftover is not None else None,
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

        for d in rows:
            results.append(
                DeliveryResponse(
                    id=d.id,
                    supplier=d.supplier,
                    carrier=d.carrier,
                    delivery_date=d.delivery_date,
                    bol_reference=d.bol_reference,
                    notes=d.notes,
                    created_by=d.created_by,
                    created_at=d.created_at,
                    items=[
                        DeliveryItemResponse.model_validate(it)
                        for it in items_map.get(d.id, [])
                    ],
                )
            )

    return DeliveryListResponse(total=total, page=page, page_size=page_size, results=results)
