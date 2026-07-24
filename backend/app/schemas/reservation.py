from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.reservation import ReservationStatus
from app.models.inventory import LotStatus

# ── Reservations ──────────────────────────────────────────────────────────────


class ReservationCreate(BaseModel):
    product_id: int = Field(..., description="The item being reserved")
    state: LotStatus = Field(
        default=LotStatus.IN_STORAGE,
        description="Stock state the reservation draws from",
    )
    quantity: int = Field(..., gt=0, description="Quantity to reserve (integer ×100)")
    production_worksheet_line_id: Optional[int] = Field(
        default=None,
        description="Owning worksheet line — populated once ACR-29 lands",
    )


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    product_name: Optional[str] = None  # denormalized for display
    state: LotStatus
    quantity: int  # integer ×100
    production_worksheet_line_id: Optional[int] = None
    status: ReservationStatus
    created_by: Optional[int] = None
    created_at: datetime
    released_at: Optional[datetime] = None


class ReservationListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[ReservationResponse]


# ── Availability ──────────────────────────────────────────────────────────────


class AvailabilityResponse(BaseModel):
    """``available = on_hand − reserved`` for one ``(item, state)`` pair.

    All quantities are integers ×100. ``available`` can go negative when stock is adjusted down
    beneath existing reservations; it is reported as-is rather than clamped.
    """

    product_id: int
    product_name: Optional[str] = None
    state: LotStatus
    on_hand: int
    reserved: int
    available: int
