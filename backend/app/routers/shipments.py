from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.shipment import ShipmentCreate, ShipmentListResponse, ShipmentResponse
from app.services import shipment_service

router = APIRouter(prefix="/api/v1/shipments", tags=["shipments"])


@router.post("", response_model=ShipmentResponse, status_code=status.HTTP_201_CREATED)
async def create_shipment(
    body: ShipmentCreate,
    current_user: TokenUser = Depends(require_privilege("shipping.create")),
    db: AsyncSession = Depends(get_db),
) -> ShipmentResponse:
    return await shipment_service.create_shipment(body, current_user, db)


@router.get("", response_model=ShipmentListResponse)
async def list_shipments(
    contact_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: TokenUser = Depends(require_privilege("shipping.view")),
    db: AsyncSession = Depends(get_db),
) -> ShipmentListResponse:
    return await shipment_service.list_shipments(
        db=db,
        contact_id=contact_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.get("/{shipment_id}", response_model=ShipmentResponse)
async def get_shipment(
    shipment_id: int,
    current_user: TokenUser = Depends(require_privilege("shipping.view")),
    db: AsyncSession = Depends(get_db),
) -> ShipmentResponse:
    return await shipment_service.get_shipment(db=db, shipment_id=shipment_id)
