from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.delivery import DeliveryCreate, DeliveryListResponse, DeliveryResponse
from app.services import delivery_service

router = APIRouter(prefix="/api/v1/deliveries", tags=["deliveries"])


@router.post("", response_model=DeliveryResponse, status_code=status.HTTP_201_CREATED)
async def create_delivery(
    body: DeliveryCreate,
    current_user: TokenUser = Depends(require_privilege("deliveries.create")),
    db: AsyncSession = Depends(get_db),
) -> DeliveryResponse:
    return await delivery_service.create_delivery(body, current_user, db)


@router.get("", response_model=DeliveryListResponse)
async def list_deliveries(
    supplier: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    bol_reference: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: TokenUser = Depends(require_privilege("deliveries.view")),
    db: AsyncSession = Depends(get_db),
) -> DeliveryListResponse:
    return await delivery_service.list_deliveries(
        db=db,
        supplier=supplier,
        carrier=carrier,
        bol_reference=bol_reference,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
