from collections import defaultdict
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.models.inventory import InventoryLot
from app.models.product import Product
from app.models.work_order import MaterialAllocation, WorkOrder, WorkOrderMaterial
from app.schemas.work_order import WorkOrderResponse
from app.services.work_order_service import _fetch_materials, _wo_response


async def allocate_materials(
    db: AsyncSession,
    wo_id: int,
    user_id: int,
) -> WorkOrderResponse:
    """FIFO pessimistic-locking allocation under SERIALIZABLE isolation."""
    # Postgres only accepts SET TRANSACTION ISOLATION LEVEL as the first statement of a
    # transaction, and by the time this runs `require_privilege` has already issued its three
    # lookups (user, roles, privileges) on this same session — so the transaction is open and the
    # SET failed with ActiveSQLTransactionError, making every allocation a 500.
    #
    # Rolling back first closes that read-only transaction so the SET lands on a fresh one. Nothing
    # is lost: the only statements so far were the RBAC reads.
    await db.rollback()
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

    needed_types = [
        m.material_type
        for m in materials
        if float(m.quantity_required) - float(m.quantity_allocated) > 0
    ]

    inv_by_type: dict[str, list] = defaultdict(list)
    if needed_types:
        inv_res = await db.execute(
            select(InventoryLot, Product.name)
            .join(Product, InventoryLot.product_id == Product.id)
            .where(
                Product.name.in_(needed_types),
                InventoryLot.status == "in_storage",
                InventoryLot.quantity_on_hand > 0,
            )
            .order_by(Product.name, InventoryLot.id.asc())
            .with_for_update()
        )
        for lot, product_name in inv_res.all():
            inv_by_type[product_name].append(lot)

    now = datetime.now(timezone.utc)

    for mat in materials:
        needed = float(mat.quantity_required) - float(mat.quantity_allocated)
        if needed <= 0:
            continue

        inventory_items = inv_by_type.get(mat.material_type, [])
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
            lot_number = getattr(inv_item, "lot_number", None) or getattr(inv_item, "lot_batch_number", None) or ""
            db.add(
                MaterialAllocation(
                    work_order_material_id=mat.id,
                    inventory_id=inv_item.id,
                    lot_batch_number=lot_number,
                    quantity_allocated=qty_taken,
                    allocated_at=now,
                )
            )
            remaining -= qty_taken

        mat.quantity_allocated = float(mat.quantity_required)

    wo.status = "materials_allocated"
    wo.updated_at = now

    await write_audit(
        db=db,
        user_id=user_id,
        action="work_order_allocated",
        entity_type="work_order",
        entity_id=wo_id,
        details={"materials_count": len(materials)},
    )
    await db.commit()

    final_materials = await _fetch_materials(db, wo_id)
    return _wo_response(wo, final_materials)
