from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.work_order import (
    WorkOrderAssign,
    WorkOrderAssignResponse,
    WorkOrderCreate,
    WorkOrderCreateResponse,
    WorkOrderListResponse,
    WorkOrderResponse,
    WorkOrderSequenceUpdate,
    WorkOrderStatusUpdate,
)
from app.services import work_order_service
from app.services import allocation_service

router = APIRouter(prefix="/api/v1/work-orders", tags=["work-orders"])


@router.post("", response_model=WorkOrderCreateResponse, status_code=201)
async def create_work_order(
    body: WorkOrderCreate,
    force: bool = Query(False),
    current_user: TokenUser = Depends(require_privilege("work_orders.create")),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderCreateResponse:
    return await work_order_service.create_work_order(
        db=db, data=body, user_id=current_user.user_id, force=force
    )


@router.get("", response_model=WorkOrderListResponse)
async def list_work_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    status: str | None = Query(None),
    production_line: str | None = Query(None),
    current_user: TokenUser = Depends(require_privilege("work_orders.view")),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderListResponse:
    return await work_order_service.list_work_orders(
        db=db,
        page=page,
        page_size=page_size,
        status_filter=status,
        production_line=production_line,
        current_user=current_user,
    )


@router.get("/{wo_id}", response_model=WorkOrderResponse)
async def get_work_order(
    wo_id: int,
    current_user: TokenUser = Depends(require_privilege("work_orders.view")),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderResponse:
    return await work_order_service.get_work_order(
        db=db, wo_id=wo_id, current_user=current_user
    )


@router.patch("/{wo_id}/assign", response_model=WorkOrderAssignResponse)
async def assign_work_order(
    wo_id: int,
    body: WorkOrderAssign,
    current_user: TokenUser = Depends(require_privilege("work_orders.assign")),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderAssignResponse:
    return await work_order_service.assign_work_order(
        db=db, wo_id=wo_id, data=body, user_id=current_user.user_id
    )


@router.patch("/{wo_id}/status", response_model=WorkOrderResponse)
async def update_status(
    wo_id: int,
    body: WorkOrderStatusUpdate,
    current_user: TokenUser = Depends(require_privilege("work_orders.status_update")),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderResponse:
    return await work_order_service.update_status(
        db=db, wo_id=wo_id, data=body, user_id=current_user.user_id
    )


@router.patch("/{wo_id}/sequence", response_model=WorkOrderResponse)
async def update_sequence(
    wo_id: int,
    body: WorkOrderSequenceUpdate,
    current_user: TokenUser = Depends(require_privilege("work_orders.sequence")),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderResponse:
    return await work_order_service.update_sequence(
        db=db, wo_id=wo_id, display_sequence=body.display_sequence, user_id=current_user.user_id
    )


@router.patch("/{wo_id}/allocate", response_model=WorkOrderResponse)
async def allocate_materials(
    wo_id: int,
    current_user: TokenUser = Depends(require_privilege("work_orders.allocate")),
    db: AsyncSession = Depends(get_db),
) -> WorkOrderResponse:
    return await allocation_service.allocate_materials(
        db=db, wo_id=wo_id, user_id=current_user.user_id
    )
