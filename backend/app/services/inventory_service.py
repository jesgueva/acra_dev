import csv
import io

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.models.delivery import Delivery, DeliveryItem
from app.models.inventory import InventoryLot, InventoryTransaction, LowStockAlert
from app.models.product import Product
from app.models.work_order import MaterialAllocation, WorkOrder, WorkOrderMaterial
from app.schemas.inventory import (
    InventoryAdjustResponse,
    InventoryLotListResponse,
    InventoryLotResponse,
    InventoryTransactionResponse,
    LocationUpdate,
    LotSplit,
    LotSplitResponse,
    LowStockAlertCreate,
    LowStockAlertListResponse,
    LowStockAlertResponse,
    TraceabilityResponse,
)


def _build_lot_query(
    status: str | None = None,
    search: str | None = None,
):
    q = select(InventoryLot)
    if status:
        q = q.where(InventoryLot.status == status)
    if search:
        q = q.join(Product, InventoryLot.product_id == Product.id, isouter=True).where(
            or_(
                Product.name.ilike(f"%{search}%"),
                InventoryLot.storage_location.ilike(f"%{search}%"),
            )
        )
    return q


async def _fetch_alert_thresholds(db: AsyncSession) -> dict[int, int]:
    alerts_res = await db.execute(select(LowStockAlert))
    return {a.product_id: a.threshold for a in alerts_res.scalars().all() if a.product_id}


async def _load_product_names(db: AsyncSession, product_ids: set[int]) -> dict[int, str]:
    if not product_ids:
        return {}
    res = await db.execute(select(Product).where(Product.id.in_(product_ids)))
    return {p.id: p.name for p in res.scalars().all()}


async def _get_lot_or_404(db: AsyncSession, lot_id: int) -> InventoryLot:
    lot = (await db.execute(select(InventoryLot).where(InventoryLot.id == lot_id))).scalar_one_or_none()
    if lot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Inventory lot not found")
    return lot


async def list_inventory(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    search: str | None = None,
) -> InventoryLotListResponse:
    base_q = _build_lot_query(status, search)

    count_res = await db.execute(select(func.count()).select_from(base_q.subquery()))
    total = count_res.scalar() or 0

    offset = (page - 1) * page_size
    lots_res = await db.execute(base_q.offset(offset).limit(page_size))
    lots = lots_res.scalars().all()

    thresholds = await _fetch_alert_thresholds(db)
    product_ids = {lot.product_id for lot in lots if lot.product_id}
    product_names = await _load_product_names(db, product_ids)

    results = []
    for lot in lots:
        thr = thresholds.get(lot.product_id) if lot.product_id else None
        results.append(
            InventoryLotResponse(
                id=lot.id,
                product_id=lot.product_id,
                product_name=product_names.get(lot.product_id) if lot.product_id else None,
                lot_number=lot.lot_number,
                storage_location=lot.storage_location,
                status=lot.status,
                quantity_on_hand=lot.quantity_on_hand,
                source_delivery_item_id=lot.source_delivery_item_id,
                pallet_number=lot.pallet_number,
                is_triggered=thr is not None and lot.quantity_on_hand <= thr,
            )
        )

    return InventoryLotListResponse(total=total, page=page, page_size=page_size, results=results)


async def adjust_quantity(
    db: AsyncSession,
    lot_id: int,
    delta: int,
    reason: str,
    user_id: int,
) -> InventoryAdjustResponse:
    lot = await _get_lot_or_404(db, lot_id)

    new_qty = lot.quantity_on_hand + delta
    if new_qty < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Adjustment would result in negative quantity ({new_qty})",
        )

    lot.quantity_on_hand = new_qty

    txn = InventoryTransaction(
        lot_id=lot.id,
        transaction_type="adjust",
        quantity=delta,
        reason=reason,
        created_by=user_id,
    )
    db.add(txn)

    await write_audit(
        db=db,
        user_id=user_id,
        action="inventory_adjust",
        entity_type="inventory_lot",
        entity_id=lot_id,
        details={"delta": delta, "new_qty": new_qty, "reason": reason},
    )
    await db.commit()

    return InventoryAdjustResponse(id=lot.id, quantity_on_hand=lot.quantity_on_hand)


async def update_location(
    db: AsyncSession,
    lot_id: int,
    data: LocationUpdate,
    user_id: int,
) -> InventoryLotResponse:
    lot = await _get_lot_or_404(db, lot_id)

    old_location = lot.storage_location
    lot.storage_location = data.storage_location

    txn = InventoryTransaction(
        lot_id=lot.id,
        transaction_type="move",
        quantity=0,
        reason=f"Location changed: {old_location} → {data.storage_location}",
        created_by=user_id,
    )
    db.add(txn)
    await db.commit()

    product_names = await _load_product_names(
        db, {lot.product_id} if lot.product_id else set()
    )
    thresholds = await _fetch_alert_thresholds(db)
    thr = thresholds.get(lot.product_id) if lot.product_id else None
    return InventoryLotResponse(
        id=lot.id,
        product_id=lot.product_id,
        product_name=product_names.get(lot.product_id) if lot.product_id else None,
        lot_number=lot.lot_number,
        storage_location=lot.storage_location,
        status=lot.status,
        quantity_on_hand=lot.quantity_on_hand,
        source_delivery_item_id=lot.source_delivery_item_id,
        pallet_number=lot.pallet_number,
        is_triggered=thr is not None and lot.quantity_on_hand <= thr,
    )


async def split_lot(
    db: AsyncSession,
    lot_id: int,
    data: LotSplit,
    user_id: int,
) -> LotSplitResponse:
    lot = await _get_lot_or_404(db, lot_id)

    if data.split_quantity > lot.quantity_on_hand:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Split quantity {data.split_quantity} exceeds lot quantity {lot.quantity_on_hand}",
        )

    lot.quantity_on_hand -= data.split_quantity

    new_lot = InventoryLot(
        product_id=lot.product_id,
        lot_number=lot.lot_number,
        storage_location=data.storage_location or lot.storage_location,
        status=lot.status,
        quantity_on_hand=data.split_quantity,
        source_delivery_item_id=lot.source_delivery_item_id,
    )
    db.add(new_lot)
    await db.flush()

    db.add(InventoryTransaction(
        lot_id=lot.id,
        transaction_type="split",
        quantity=-data.split_quantity,
        reason=f"Split to lot {new_lot.id}",
        created_by=user_id,
    ))
    db.add(InventoryTransaction(
        lot_id=new_lot.id,
        transaction_type="split",
        quantity=data.split_quantity,
        reason=f"Split from lot {lot.id}",
        created_by=user_id,
    ))

    await db.commit()

    return LotSplitResponse(
        source_lot=InventoryAdjustResponse(id=lot.id, quantity_on_hand=lot.quantity_on_hand),
        new_lot_id=new_lot.id,
        new_lot_quantity=new_lot.quantity_on_hand,
    )


async def list_transactions(
    db: AsyncSession,
    lot_id: int,
) -> list[InventoryTransactionResponse]:
    res = await db.execute(
        select(InventoryTransaction)
        .where(InventoryTransaction.lot_id == lot_id)
        .order_by(InventoryTransaction.created_at.desc())
    )
    txns = res.scalars().all()
    return [InventoryTransactionResponse.model_validate(t) for t in txns]


async def trace_lot(db: AsyncSession, lot_number: str) -> TraceabilityResponse:
    lots_res = await db.execute(
        select(InventoryLot).where(InventoryLot.lot_number == lot_number)
    )
    lots = lots_res.scalars().all()

    product_ids = {lot.product_id for lot in lots if lot.product_id}
    product_names = await _load_product_names(db, product_ids)

    lots_data = [
        {
            "id": lot.id,
            "product_id": lot.product_id,
            "product_name": product_names.get(lot.product_id) if lot.product_id else None,
            "status": lot.status,
            "quantity_on_hand": lot.quantity_on_hand,
            "storage_location": lot.storage_location,
        }
        for lot in lots
    ]

    source_delivery = None
    source_ids = [lot.source_delivery_item_id for lot in lots if lot.source_delivery_item_id]
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
                    "contact_id": d.contact_id,
                    "carrier_id": d.carrier_id,
                    "delivery_date": str(d.delivery_date),
                    "bol_reference": d.bol_reference,
                }

    alloc_res = await db.execute(
        select(MaterialAllocation).where(MaterialAllocation.lot_batch_number == lot_number)
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
        lot_number=lot_number,
        source_delivery=source_delivery,
        lots=lots_data,
        work_orders=work_orders,
    )


async def list_alerts(db: AsyncSession) -> LowStockAlertListResponse:
    alerts_res = await db.execute(select(LowStockAlert))
    alerts = alerts_res.scalars().all()

    product_ids = {a.product_id for a in alerts if a.product_id}
    product_names = await _load_product_names(db, product_ids)

    qty_res = await db.execute(
        select(InventoryLot.product_id, func.sum(InventoryLot.quantity_on_hand).label("total"))
        .group_by(InventoryLot.product_id)
    )
    qty_map = {row[0]: row[1] for row in qty_res.all() if row[0] is not None}

    alert_responses = []
    for alert in alerts:
        current_qty = qty_map.get(alert.product_id, 0)
        thr = alert.threshold
        alert_responses.append(
            LowStockAlertResponse(
                id=alert.id,
                product_id=alert.product_id,
                product_name=product_names.get(alert.product_id) if alert.product_id else None,
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
        select(LowStockAlert).where(LowStockAlert.product_id == data.product_id)
    )
    existing = res.scalar_one_or_none()

    if existing:
        existing.threshold = data.threshold
        alert = existing
    else:
        alert = LowStockAlert(
            product_id=data.product_id,
            threshold=data.threshold,
            created_by=user_id,
        )
        db.add(alert)
        await db.flush()  # assigns PK before we read alert.id

    await db.commit()

    product_names = await _load_product_names(
        db, {data.product_id} if data.product_id else set()
    )
    current_qty = 0
    if data.product_id:
        qty_res = await db.execute(
            select(func.sum(InventoryLot.quantity_on_hand)).where(
                InventoryLot.product_id == data.product_id
            )
        )
        current_qty = qty_res.scalar() or 0
    return LowStockAlertResponse(
        id=alert.id,
        product_id=alert.product_id,
        product_name=product_names.get(data.product_id) if data.product_id else None,
        threshold=alert.threshold,
        current_quantity=current_qty,
        is_triggered=current_qty <= alert.threshold,
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
    status_filter: str | None = None,
    search: str | None = None,
) -> str:
    base_q = _build_lot_query(status_filter, search)

    lots_res = await db.execute(base_q)
    lots = lots_res.scalars().all()

    product_ids = {lot.product_id for lot in lots if lot.product_id}
    product_names = await _load_product_names(db, product_ids)
    thresholds = await _fetch_alert_thresholds(db)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "product_name", "lot_number", "status",
        "quantity_on_hand", "storage_location", "is_triggered",
    ])
    for lot in lots:
        pname = product_names.get(lot.product_id, "") if lot.product_id else ""
        thr = thresholds.get(lot.product_id) if lot.product_id else None
        writer.writerow([
            lot.id,
            pname,
            lot.lot_number,
            lot.status,
            lot.quantity_on_hand,
            lot.storage_location,
            thr is not None and lot.quantity_on_hand <= thr,
        ])

    return output.getvalue()
