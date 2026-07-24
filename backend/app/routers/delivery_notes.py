from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_any_privilege
from app.schemas.auth import TokenUser
from app.schemas.delivery_note import DeliveryNoteListResponse, DeliveryNoteResponse
from app.services import delivery_note_service

router = APIRouter(prefix="/api/v1/delivery-notes", tags=["delivery-notes"])

# Read-only by design. A note exists to justify a stock movement (§4.1), so notes are created as a
# side effect of receiving, shipping, and worksheet approval — never on their own. A bare POST
# would let a note exist with no movement behind it, inverting the invariant this table enforces.


@router.get("", response_model=DeliveryNoteListResponse)
async def list_delivery_notes(
    type: Optional[str] = Query(None),
    partner_id: Optional[int] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: TokenUser = Depends(
        require_any_privilege("deliveries.view", "shipping.view")
    ),
    db: AsyncSession = Depends(get_db),
) -> DeliveryNoteListResponse:
    return await delivery_note_service.list_notes(
        db=db,
        type_filter=type,
        partner_id=partner_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )


@router.get("/{note_id}", response_model=DeliveryNoteResponse)
async def get_delivery_note(
    note_id: int,
    current_user: TokenUser = Depends(
        require_any_privilege("deliveries.view", "shipping.view")
    ),
    db: AsyncSession = Depends(get_db),
) -> DeliveryNoteResponse:
    return await delivery_note_service.get_note(db=db, note_id=note_id)
