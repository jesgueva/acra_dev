import csv
import io
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.models.delivery import Delivery, DeliveryItem
from app.models.inventory import InventoryItem, LowStockAlert
from app.models.work_order import MaterialAllocation, WorkOrder, WorkOrderMaterial
from app.schemas.inventory import (
    InventoryAdjustResponse,
    InventoryListResponse,
    InventoryResponse,
    LowStockAlertCreate,
    LowStockAlertListResponse,
    LowStockAlertResponse,
    TraceabilityResponse,
)


def _build_item_query(
    category: str | None = None,
    item_name: str | None = None,
    storage_location: str | None = None,
):
    q = select(InventoryItem)
    if category:
        q = q.where(InventoryItem.category == category)
    if item_name:
        q = q.where(InventoryItem.item_name.ilike(f"%{item_name}%"))
    if storage_location:
        q = q.where(InventoryItem.storage_location.ilike(f"%{storage_location}%"))
    return q


async def _fetch_thresholds(db: AsyncSession) -> dict[str, float]:
    alerts_res = await db.execute(select(LowStockAlert))
    return {a.item_name: float(a.threshold) for a in alerts_res.scalars().all()}


async def list_inventory(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    category: str | None = None,
    item_name: str | None = None,
    storage_location: str | None = None,
) -> InventoryListResponse:
    base_q = _build_item_query(category, item_name, storage_location)

    count_res = await db.execute(select(func.count()).select_from(base_q.subquery()))
    total = count_res.scalar() or 0

    offset = (page - 1) * page_size
    items_res = await db.execute(base_q.offset(offset).limit(page_size))
    items = items_res.scalars().all()

    thresholds = await _fetch_thresholds(db)

    results = []
    for item in items:
        qty = float(item.quantity_on_hand)
        thr = thresholds.get(item.item_name)
        results.append(
            InventoryResponse(
                id=item.id,
                item_name=item.item_name,
                category=item.category,
                quantity_on_hand=qty,
                lot_batch_number=item.lot_batch_number,
                storage_location=item.storage_location,
                source_delivery_item_id=item.source_delivery_item_id,
                last_updated=item.last_updated,
                is_triggered=thr is not None and qty <= thr,
            )
        )

    return InventoryListResponse(total=total, page=page, page_size=page_size, results=results)


async def adjust_quantity(
    db: AsyncSession,
    item_id: int,
    quantity_on_hand: float,
    reason: str,
    user_id: int,
) -> InventoryAdjustResponse:
    res = await db.execute(select(InventoryItem).where(InventoryItem.id == item_id))
    item = res.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory item not found")

    item.quantity_on_hand = quantity_on_hand
    item.last_updated = datetime.now(timezone.utc)

    await write_audit(
        db=db,
        user_id=user_id,
        action="inventory_adjust",
        entity_type="inventory_item",
        entity_id=item_id,
        details={"quantity_on_hand": quantity_on_hand, "reason": reason},
    )
    await db.commit()

    return InventoryAdjustResponse(
        id=item.id,
        quantity_on_hand=float(item.quantity_on_hand),
        last_updated=item.last_updated,
    )


async def trace_lot(db: AsyncSession, lot_batch_number: str) -> TraceabilityResponse:
    items_res = await db.execute(
        select(InventoryItem).where(InventoryItem.lot_batch_number == lot_batch_number)
    )
    items = items_res.scalars().all()

    inventory_items_data = [
        {
            "id": i.id,
            "item_name": i.item_name,
            "category": i.category,
            "quantity_on_hand": float(i.quantity_on_hand),
            "storage_location": i.storage_location,
        }
        for i in items
    ]

    source_delivery = None
    source_ids = [i.source_delivery_item_id for i in items if i.source_delivery_item_id]
    if source_ids:
        di_res = await db.execute(
            select(DeliveryItem).where(DeliveryItem.id == source_ids[0])
        )
        di = di_res.scalar_one_or_none()
        if di:
            d_res = await db.execute(select(Delivery).where(Delivery.id == di.delivery_id))
            d = d_res.scalar_one_or_none()
            if d:
                source_delivery = {
                    "delivery_id": d.id,
                    "supplier": d.supplier,
                    "carrier": d.carrier,
                    "delivery_date": str(d.delivery_date),
                    "bol_reference": d.bol_reference,
                }

    alloc_res = await db.execute(
        select(MaterialAllocation).where(MaterialAllocation.lot_batch_number == lot_batch_number)
    )
    allocations = alloc_res.scalars().all()

    work_orders = []
    if allocations:
        wom_ids = list({a.work_order_material_id for a in allocations})
        wom_res = await db.execute(
            select(WorkOrderMaterial).where(WorkOrderMaterial.id.in_(wom_ids))
        )
        woms = wom_res.scalars().all()
        wo_ids = list({w.work_order_id for w in woms})
        if wo_ids:
            wo_res = await db.execute(
                select(WorkOrder).where(WorkOrder.id.in_(wo_ids))
            )
            wos = wo_res.scalars().all()
            work_orders = [
                {"work_order_id": wo.id, "product": wo.product, "status": wo.status}
                for wo in wos
            ]

    return TraceabilityResponse(
        lot_batch_number=lot_batch_number,
        source_delivery=source_delivery,
        inventory_items=inventory_items_data,
        work_orders=work_orders,
    )


async def list_alerts(db: AsyncSession) -> LowStockAlertListResponse:
    alerts_res = await db.execute(select(LowStockAlert))
    alerts = alerts_res.scalars().all()

    qty_res = await db.execute(
        select(InventoryItem.item_name, func.sum(InventoryItem.quantity_on_hand).label("total"))
        .group_by(InventoryItem.item_name)
    )
    qty_map = {row[0]: float(row[1]) for row in qty_res.all()}

    alert_responses = []
    for alert in alerts:
        current_qty = qty_map.get(alert.item_name, 0.0)
        thr = float(alert.threshold)
        alert_responses.append(
            LowStockAlertResponse(
                id=alert.id,
                item_name=alert.item_name,
                threshold=thr,
                current_quantity=current_qty,
                is_triggered=current_qty <= thr,
            )
        )

    return LowStockAlertListResponse(alerts=alert_responses)


async def create_alert(
    db: AsyncSession,
    data: LowStockAlertCreate,
    user_id: int,
) -> LowStockAlertResponse:
    res = await db.execute(
        select(LowStockAlert).where(LowStockAlert.item_name == data.item_name)
    )
    existing = res.scalar_one_or_none()

    if existing:
        existing.threshold = data.threshold
        alert = existing
    else:
        alert = LowStockAlert(
            item_name=data.item_name,
            threshold=data.threshold,
            created_by=user_id,
        )
        db.add(alert)

    await db.commit()

    return LowStockAlertResponse(
        id=alert.id or 0,
        item_name=alert.item_name,
        threshold=float(alert.threshold),
        current_quantity=0.0,
        is_triggered=False,
    )


async def delete_alert(db: AsyncSession, alert_id: int) -> None:
    res = await db.execute(select(LowStockAlert).where(LowStockAlert.id == alert_id))
    alert = res.scalar_one_or_none()
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

    await db.delete(alert)
    await db.commit()


async def export_csv(
    db: AsyncSession,
    category: str | None = None,
    item_name: str | None = None,
    storage_location: str | None = None,
) -> str:
    base_q = _build_item_query(category, item_name, storage_location)

    items_res = await db.execute(base_q)
    items = items_res.scalars().all()

    thresholds = await _fetch_thresholds(db)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "item_name", "category", "quantity_on_hand",
        "lot_batch_number", "storage_location", "last_updated", "is_triggered",
    ])
    for item in items:
        qty = float(item.quantity_on_hand)
        thr = thresholds.get(item.item_name)
        writer.writerow([
            item.id,
            item.item_name,
            item.category,
            qty,
            item.lot_batch_number,
            item.storage_location,
            item.last_updated.isoformat(),
            thr is not None and qty <= thr,
        ])

    return output.getvalue()
