from typing import List

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.inventory import (
    InventoryAdjust,
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
from app.services import inventory_service

router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("", response_model=InventoryLotListResponse)
async def list_inventory(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    status: str | None = Query(None),
    search: str | None = Query(None),
    current_user: TokenUser = Depends(require_privilege("inventory.view")),
    db: AsyncSession = Depends(get_db),
) -> InventoryLotListResponse:
    return await inventory_service.list_inventory(
        db=db,
        page=page,
        page_size=page_size,
        status=status,
        search=search,
    )


@router.get("/export")
async def export_csv(
    status: str | None = Query(None),
    search: str | None = Query(None),
    current_user: TokenUser = Depends(require_privilege("inventory.view")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    content = await inventory_service.export_csv(
        db=db,
        status_filter=status,
        search=search,
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
    await inventory_service.delete_alert(db=db, alert_id=alert_id)


@router.get("/trace/{lot_number}", response_model=TraceabilityResponse)
async def trace_lot(
    lot_number: str,
    current_user: TokenUser = Depends(require_privilege("inventory.view")),
    db: AsyncSession = Depends(get_db),
) -> TraceabilityResponse:
    return await inventory_service.trace_lot(db=db, lot_number=lot_number)


@router.get("/lots/{lot_id}/transactions", response_model=List[InventoryTransactionResponse])
async def list_transactions(
    lot_id: int,
    current_user: TokenUser = Depends(require_privilege("inventory.view")),
    db: AsyncSession = Depends(get_db),
) -> List[InventoryTransactionResponse]:
    return await inventory_service.list_transactions(db=db, lot_id=lot_id)


@router.patch("/lots/{lot_id}/location", response_model=InventoryLotResponse)
async def update_location(
    lot_id: int,
    body: LocationUpdate,
    current_user: TokenUser = Depends(require_privilege("inventory.adjust")),
    db: AsyncSession = Depends(get_db),
) -> InventoryLotResponse:
    return await inventory_service.update_location(
        db=db,
        lot_id=lot_id,
        data=body,
        user_id=current_user.user_id,
    )


@router.post("/lots/{lot_id}/split", response_model=LotSplitResponse, status_code=201)
async def split_lot(
    lot_id: int,
    body: LotSplit,
    current_user: TokenUser = Depends(require_privilege("inventory.adjust")),
    db: AsyncSession = Depends(get_db),
) -> LotSplitResponse:
    return await inventory_service.split_lot(
        db=db,
        lot_id=lot_id,
        data=body,
        user_id=current_user.user_id,
    )


@router.patch("/{lot_id}", response_model=InventoryAdjustResponse)
async def adjust_quantity(
    lot_id: int,
    body: InventoryAdjust,
    current_user: TokenUser = Depends(require_privilege("inventory.adjust")),
    db: AsyncSession = Depends(get_db),
) -> InventoryAdjustResponse:
    return await inventory_service.adjust_quantity(
        db=db,
        lot_id=lot_id,
        delta=body.delta,
        reason=body.reason,
        user_id=current_user.user_id,
    )
