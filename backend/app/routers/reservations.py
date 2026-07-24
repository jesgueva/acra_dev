from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.models.inventory import LotStatus
from app.models.reservation import ReservationStatus
from app.schemas.auth import TokenUser
from app.schemas.reservation import (
    ReservationCreate,
    ReservationListResponse,
    ReservationResponse,
)
from app.services import reservation_service

router = APIRouter(prefix="/api/v1/reservations", tags=["reservations"])


@router.post("", response_model=ReservationResponse, status_code=201)
async def create_reservation(
    body: ReservationCreate,
    current_user: TokenUser = Depends(require_privilege("inventory.reserve")),
    db: AsyncSession = Depends(get_db),
) -> ReservationResponse:
    return await reservation_service.reserve(
        db=db,
        data=body,
        user_id=current_user.user_id,
    )


@router.post("/{reservation_id}/release", response_model=ReservationResponse)
async def release_reservation(
    reservation_id: int,
    current_user: TokenUser = Depends(require_privilege("inventory.reserve")),
    db: AsyncSession = Depends(get_db),
) -> ReservationResponse:
    return await reservation_service.release(
        db=db,
        reservation_id=reservation_id,
        user_id=current_user.user_id,
    )


@router.get("", response_model=ReservationListResponse)
async def list_reservations(
    product_id: int | None = Query(None),
    state: LotStatus | None = Query(None),
    status: ReservationStatus | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=250),
    current_user: TokenUser = Depends(require_privilege("inventory.view")),
    db: AsyncSession = Depends(get_db),
) -> ReservationListResponse:
    return await reservation_service.list_reservations(
        db=db,
        product_id=product_id,
        state=state,
        status_filter=status,
        page=page,
        page_size=page_size,
    )
