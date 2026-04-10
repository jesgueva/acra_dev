from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.models.inventory import InventoryLot
from app.models.product import Product
from app.models.work_order import WorkOrder, WorkOrderMaterial
from app.schemas.auth import TokenUser
from app.schemas.work_order import (
    MaterialAvailability,
    WorkOrderAssign,
    WorkOrderAssignResponse,
    WorkOrderCreate,
    WorkOrderCreateResponse,
    WorkOrderListResponse,
    WorkOrderMaterialResponse,
    WorkOrderResponse,
    WorkOrderStatusUpdate,
)

_ACTIVE_STATUSES = ("created", "materials_allocated", "in_production")


def _wo_response(wo: WorkOrder, materials: list) -> WorkOrderResponse:
    wo_id = wo.id or 0
    return WorkOrderResponse(
        id=wo_id,
        wo_number=f"WO-{wo_id:04d}",
        product=wo.product,
        status=wo.status,
        priority=wo.priority,
        display_sequence=wo.display_sequence,
        production_line=wo.production_line,
        target_date=wo.target_date,
        quantity_required=float(wo.quantity_required),
        quantity_produced=float(wo.quantity_produced),
        created_by=wo.created_by,
        created_at=wo.created_at,
        updated_at=wo.updated_at,
        materials=[
            WorkOrderMaterialResponse(
                id=m.id,
                material_type=m.material_type,
                quantity_required=float(m.quantity_required),
                quantity_allocated=float(m.quantity_allocated),
            )
            for m in materials
        ],
    )


async def _fetch_wo_or_404(db: AsyncSession, wo_id: int) -> WorkOrder:
    res = await db.execute(select(WorkOrder).where(WorkOrder.id == wo_id))
    wo = res.scalar_one_or_none()
    if wo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work order not found")
    return wo


async def _fetch_materials(db: AsyncSession, wo_id: int) -> list:
    res = await db.execute(
        select(WorkOrderMaterial).where(WorkOrderMaterial.work_order_id == wo_id)
    )
    return res.scalars().all()


async def create_work_order(
    db: AsyncSession,
    data: WorkOrderCreate,
    user_id: int,
    force: bool = False,
) -> WorkOrderCreateResponse:
    dup_res = await db.execute(
        select(WorkOrder).where(
            WorkOrder.product == data.product,
            WorkOrder.quantity_required == data.quantity_required,
            WorkOrder.target_date == data.target_date,
        )
    )
    dup = dup_res.scalar_one_or_none()
    if dup is not None and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate work order. Use force=true to override.",
        )

    material_types = [m.material_type for m in data.materials]
    qty_res = await db.execute(
        select(
            Product.name,
            func.sum(InventoryLot.quantity_on_hand).label("total"),
        )
        .join(Product, InventoryLot.product_id == Product.id)
        .where(Product.name.in_(material_types))
        .where(InventoryLot.status == "in_storage")
        .group_by(Product.name)
    )
    qty_map = {row[0]: float(row[1]) for row in qty_res.all()}

    availability: list[MaterialAvailability] = []
    hard_block = False
    for m in data.materials:
        available = qty_map.get(m.material_type, 0.0)
        if available == 0.0:
            hard_block = True
        availability.append(
            MaterialAvailability(
                material_type=m.material_type,
                required=m.quantity_required,
                available=available,
                sufficient=available >= m.quantity_required,
            )
        )

    if hard_block:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="One or more materials have zero available quantity.",
        )

    wo = WorkOrder(
        product=data.product,
        quantity_required=data.quantity_required,
        priority=data.priority,
        status="created",
        target_date=data.target_date,
        production_line=data.production_line,
        created_by=user_id,
    )
    db.add(wo)
    await db.flush()  # populates wo.id from the DB sequence

    for m in data.materials:
        db.add(WorkOrderMaterial(
            work_order_id=wo.id,
            material_type=m.material_type,
            quantity_required=m.quantity_required,
        ))

    await write_audit(
        db=db,
        user_id=user_id,
        action="work_order_created",
        entity_type="work_order",
        entity_id=wo.id,
        details={"product": data.product},
    )
    await db.commit()

    wo_id = wo.id or 0
    return WorkOrderCreateResponse(
        id=wo_id,
        wo_number=f"WO-{wo_id:04d}",
        status=wo.status,
        material_availability=availability,
    )


async def list_work_orders(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    status_filter: Optional[str] = None,
    production_line: Optional[str] = None,
    current_user: Optional[TokenUser] = None,
) -> WorkOrderListResponse:
    q = select(WorkOrder)

    if current_user and "machine_operator" in current_user.roles:
        if current_user.production_line:
            q = q.where(WorkOrder.production_line == current_user.production_line)
    elif production_line:
        q = q.where(WorkOrder.production_line == production_line)

    if status_filter:
        q = q.where(WorkOrder.status == status_filter)

    count_res = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_res.scalar() or 0

    offset = (page - 1) * page_size
    wos_res = await db.execute(q.offset(offset).limit(page_size))
    wos = wos_res.scalars().all()

    # Fetch all materials for the page in one query instead of one per WO
    wo_ids = [wo.id for wo in wos if wo.id is not None]
    if wo_ids:
        mats_res = await db.execute(
            select(WorkOrderMaterial).where(WorkOrderMaterial.work_order_id.in_(wo_ids))
        )
        mats_by_wo: dict[int, list] = {wid: [] for wid in wo_ids}
        for m in mats_res.scalars().all():
            mats_by_wo[m.work_order_id].append(m)
    else:
        mats_by_wo = {}

    results = [_wo_response(wo, mats_by_wo.get(wo.id or 0, [])) for wo in wos]
    return WorkOrderListResponse(total=total, page=page, page_size=page_size, results=results)


async def get_work_order(
    db: AsyncSession,
    wo_id: int,
    current_user: Optional[TokenUser] = None,
) -> WorkOrderResponse:
    wo = await _fetch_wo_or_404(db, wo_id)

    if current_user and "machine_operator" in current_user.roles:
        if current_user.production_line and wo.production_line != current_user.production_line:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: work order is on a different production line.",
            )

    materials = await _fetch_materials(db, wo_id)
    return _wo_response(wo, materials)


async def assign_work_order(
    db: AsyncSession,
    wo_id: int,
    data: WorkOrderAssign,
    user_id: int,
) -> WorkOrderAssignResponse:
    wo = await _fetch_wo_or_404(db, wo_id)

    count_res = await db.execute(
        select(func.count()).where(
            WorkOrder.production_line == data.production_line,
            WorkOrder.status.in_(_ACTIVE_STATUSES),
            WorkOrder.id != wo_id,
        )
    )
    active_count = count_res.scalar() or 0
    capacity_warning: Optional[str] = None
    if active_count >= 3:
        capacity_warning = (
            f"Production line '{data.production_line}' already has "
            f"{active_count} active work orders."
        )

    wo.production_line = data.production_line
    wo.updated_at = datetime.now(timezone.utc)

    await write_audit(
        db=db,
        user_id=user_id,
        action="work_order_assigned",
        entity_type="work_order",
        entity_id=wo_id,
        details={"production_line": data.production_line},
    )
    await db.commit()

    materials = await _fetch_materials(db, wo_id)
    return WorkOrderAssignResponse(
        **_wo_response(wo, materials).model_dump(),
        capacity_warning=capacity_warning,
    )


async def update_status(
    db: AsyncSession,
    wo_id: int,
    data: WorkOrderStatusUpdate,
    user_id: int,
) -> WorkOrderResponse:
    wo = await _fetch_wo_or_404(db, wo_id)

    wo.status = data.status
    wo.updated_at = datetime.now(timezone.utc)

    if data.quantity_produced is not None:
        wo.quantity_produced = data.quantity_produced

    if data.status == "completed":
        qty_produced = (
            data.quantity_produced
            if data.quantity_produced is not None
            else float(wo.quantity_produced)
        )
        db.add(InventoryLot(
            lot_number=f"WO-{(wo.id or 0):04d}",
            storage_location="FINISHED_GOODS",
            status="in_storage",
            quantity_on_hand=int(qty_produced * 100),  # convert to ×100 integer
            # product_id left None until work orders are linked to Product entities
        ))

    await write_audit(
        db=db,
        user_id=user_id,
        action="work_order_status_updated",
        entity_type="work_order",
        entity_id=wo_id,
        details={"status": data.status},
    )
    await db.commit()

    materials = await _fetch_materials(db, wo_id)
    return _wo_response(wo, materials)


async def update_sequence(
    db: AsyncSession,
    wo_id: int,
    display_sequence: int,
    user_id: int,
) -> WorkOrderResponse:
    wo = await _fetch_wo_or_404(db, wo_id)
    wo.display_sequence = display_sequence
    wo.updated_at = datetime.now(timezone.utc)
    await db.commit()

    materials = await _fetch_materials(db, wo_id)
    return _wo_response(wo, materials)
