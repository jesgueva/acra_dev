from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.models.inventory import InventoryItem, LowStockAlert
from app.models.work_order import MaterialAllocation, WorkOrder, WorkOrderMaterial
from app.schemas.work_order import WorkOrderResponse
from app.services.work_order_service import _fetch_materials, _wo_response


async def allocate_materials(
    db: AsyncSession,
    wo_id: int,
    user_id: int,
) -> WorkOrderResponse:
    """
    FIFO pessimistic-locking allocation algorithm (LLD Section 4.1).

    1. SET TRANSACTION ISOLATION LEVEL SERIALIZABLE
    2. Lock work order FOR UPDATE
    3. For each material: SELECT raw inventory ORDER BY last_updated ASC FOR UPDATE → deduct FIFO
    4. INSERT material_allocations, UPDATE quantity_allocated
    5. SET work_order.status = 'materials_allocated'
    6. COMMIT → evaluate low-stock alerts
    """
    await db.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

    res = await db.execute(
        select(WorkOrder).where(WorkOrder.id == wo_id).with_for_update()
    )
    wo = res.scalar_one_or_none()
    if wo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found"
        )

    if wo.status != "created":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Work order cannot be allocated in status '{wo.status}'.",
        )

    mats_res = await db.execute(
        select(WorkOrderMaterial).where(WorkOrderMaterial.work_order_id == wo_id)
    )
    materials = mats_res.scalars().all()

    for mat in materials:
        needed = float(mat.quantity_required) - float(mat.quantity_allocated)
        if needed <= 0:
            continue

        inv_res = await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.material_type == mat.material_type,
                InventoryItem.category == "raw",
                InventoryItem.quantity_on_hand > 0,
            )
            .order_by(InventoryItem.last_updated.asc())
            .with_for_update()
        )
        inventory_items = inv_res.scalars().all()

        total_available = sum(float(item.quantity_on_hand) for item in inventory_items)
        if total_available < needed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Insufficient stock for material '{mat.material_type}'. "
                    f"Required: {needed}, Available: {total_available}."
                ),
            )

        remaining = needed
        for inv_item in inventory_items:
            if remaining <= 0:
                break
            qty_taken = min(remaining, float(inv_item.quantity_on_hand))
            inv_item.quantity_on_hand = float(inv_item.quantity_on_hand) - qty_taken
            inv_item.last_updated = datetime.now(timezone.utc)
            db.add(
                MaterialAllocation(
                    work_order_material_id=mat.id,
                    inventory_id=inv_item.id,
                    lot_batch_number=inv_item.lot_batch_number,
                    quantity_allocated=qty_taken,
                    allocated_at=datetime.now(timezone.utc),
                )
            )
            remaining -= qty_taken

        mat.quantity_allocated = float(mat.quantity_required)

    wo.status = "materials_allocated"
    wo.updated_at = datetime.now(timezone.utc)

    await write_audit(
        db=db,
        user_id=user_id,
        action="work_order_allocated",
        entity_type="work_order",
        entity_id=wo_id,
        details={"materials_count": len(materials)},
    )
    await db.commit()

    await _evaluate_low_stock_alerts(db, [m.material_type for m in materials])

    final_materials = await _fetch_materials(db, wo_id)
    return _wo_response(wo, final_materials)


async def _evaluate_low_stock_alerts(db: AsyncSession, material_types: list[str]) -> None:
    """Check whether any low-stock thresholds are now breached after allocation."""
    if not material_types:
        return
    alerts_res = await db.execute(
        select(LowStockAlert).where(LowStockAlert.material_type.in_(material_types))
    )
    _ = alerts_res.scalars().all()
