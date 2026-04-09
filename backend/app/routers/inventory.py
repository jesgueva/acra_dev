from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.inventory import (
    InventoryAdjust,
    InventoryAdjustResponse,
    InventoryListResponse,
    LowStockAlertCreate,
    LowStockAlertListResponse,
    LowStockAlertResponse,
    TraceabilityResponse,
)
from app.services import inventory_service

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("", response_model=InventoryListResponse)
async def list_inventory(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    category: str | None = Query(None),
    material_type: str | None = Query(None),
    storage_location: str | None = Query(None),
    current_user: TokenUser = Depends(require_privilege("inventory.view")),
    db: AsyncSession = Depends(get_db),
) -> InventoryListResponse:
    return await inventory_service.list_inventory(
        db=db,
        page=page,
        page_size=page_size,
        category=category,
        material_type=material_type,
        storage_location=storage_location,
    )


@router.get("/export")
async def export_csv(
    category: str | None = Query(None),
    material_type: str | None = Query(None),
    storage_location: str | None = Query(None),
    current_user: TokenUser = Depends(require_privilege("inventory.view")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content = await inventory_service.export_csv(
        db=db,
        category=category,
        material_type=material_type,
        storage_location=storage_location,
    )
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=inventory.csv"},
    )


@router.get("/alerts", response_model=LowStockAlertListResponse)
async def list_alerts(
    current_user: TokenUser = Depends(require_privilege("inventory.view")),
    db: AsyncSession = Depends(get_db),
) -> LowStockAlertListResponse:
    return await inventory_service.list_alerts(db=db)


@router.post("/alerts", response_model=LowStockAlertResponse, status_code=201)
async def create_alert(
    body: LowStockAlertCreate,
    current_user: TokenUser = Depends(require_privilege("inventory.adjust")),
    db: AsyncSession = Depends(get_db),
) -> LowStockAlertResponse:
    return await inventory_service.create_alert(db=db, data=body, user_id=current_user.user_id)


@router.delete("/alerts/{alert_id}", status_code=204)
async def delete_alert(
    alert_id: int,
    current_user: TokenUser = Depends(require_privilege("inventory.adjust")),
    db: AsyncSession = Depends(get_db),
) -> None:
    await inventory_service.delete_alert(db=db, alert_id=alert_id, user_id=current_user.user_id)


@router.get("/trace/{lot_batch_number}", response_model=TraceabilityResponse)
async def trace_lot(
    lot_batch_number: str,
    current_user: TokenUser = Depends(require_privilege("inventory.view")),
    db: AsyncSession = Depends(get_db),
) -> TraceabilityResponse:
    return await inventory_service.trace_lot(db=db, lot_batch_number=lot_batch_number)


@router.patch("/{item_id}", response_model=InventoryAdjustResponse)
async def adjust_quantity(
    item_id: int,
    body: InventoryAdjust,
    current_user: TokenUser = Depends(require_privilege("inventory.adjust")),
    db: AsyncSession = Depends(get_db),
) -> InventoryAdjustResponse:
    return await inventory_service.adjust_quantity(
        db=db,
        item_id=item_id,
        quantity_on_hand=body.quantity_on_hand,
        reason=body.reason,
        user_id=current_user.user_id,
    )
