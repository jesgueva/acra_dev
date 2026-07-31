from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Item schemas ──────────────────────────────────────────────────────────────

class DeliveryItemCreate(BaseModel):
    product_id: int
    description: Optional[str] = None
    quantity: int = Field(..., gt=0)      # integer ×100 (5000 = 50.00 units)
    pallets: Optional[int] = None
    units_per_pallet: Optional[int] = None


class DeliveryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: Optional[int] = None
    product_name: Optional[str] = None   # denormalized for display
    description: Optional[str] = None
    quantity: int                         # integer ×100
    pallets: Optional[int] = None
    units_per_pallet: Optional[int] = None
    leftover: Optional[int] = None       # integer ×100
    inventory_lot_id: Optional[int] = None


# ── Delivery schemas ──────────────────────────────────────────────────────────

class DeliveryCreate(BaseModel):
    contact_id: Optional[int] = None     # provider contact
    carrier_id: Optional[int] = None     # carrier contact
    bol_reference: str = Field(..., max_length=100)
    delivery_date: str = Field(..., max_length=20)
    notes: Optional[str] = None
    force: bool = False
    items: List[DeliveryItemCreate] = Field(..., min_length=1)


class DeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_note_id: Optional[int] = None
    # `contact_id`, `delivery_date` and `bol_reference` are projected from the linked delivery
    # note, which is their only storage location since migration 011. Kept flat here so the
    # shipped receiving UI and its API contract are unchanged.
    contact_id: Optional[int] = None
    contact_name: Optional[str] = None   # denormalized
    carrier_id: Optional[int] = None
    carrier_name: Optional[str] = None   # denormalized
    delivery_date: str
    bol_reference: str
    notes: Optional[str] = None
    created_by: int
    created_by_name: Optional[str] = None  # User.full_name for display
    created_at: datetime
    items: List[DeliveryItemResponse] = []


class DeliveryListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[DeliveryResponse]


# ── OCR schemas ───────────────────────────────────────────────────────────────

class OCRItemResult(BaseModel):
    item_name: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    pallets: Optional[int] = None
    units_per_pallet: Optional[int] = None


class OCRResponse(BaseModel):
    """A BOL extraction.

    On `confidence`: it is the fraction of the four header fields that came back **non-empty** — a
    measure of *presence*, not of *correctness*. Four wrong header values still score 1.0. It is
    kept as-is because the endpoint's 422 gate and the Gemini→Claude fallback both key off
    `> 0.0`, but it must never be read as accuracy. `header_fill_rate` is the same number under a
    name that says what it actually is.

    Real accuracy is measured out-of-band against a labelled corpus by the A8-4 bench
    (`backend/scripts/ocr_bench/`), which scores header fields and line items against ground truth.
    """

    supplier: Optional[str] = None
    carrier: Optional[str] = None
    bol_reference: Optional[str] = None
    delivery_date: Optional[str] = None
    items: List[OCRItemResult] = []
    confidence: float = 0.0
    #: Fraction of the four header fields that are non-empty. The same number as `confidence`,
    #: named honestly: presence, not correctness.
    header_fill_rate: float = 0.0
    #: Which model actually answered — "gemini" or "claude". Without it a caller cannot tell
    #: whether the primary succeeded or the fallback carried the request.
    provider: Optional[str] = None
