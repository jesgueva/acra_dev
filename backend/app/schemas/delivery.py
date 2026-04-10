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
    contact_id: Optional[int] = None
    contact_name: Optional[str] = None   # denormalized
    carrier_id: Optional[int] = None
    carrier_name: Optional[str] = None   # denormalized
    delivery_date: str
    bol_reference: str
    notes: Optional[str] = None
    created_by: int
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
    supplier: Optional[str] = None
    carrier: Optional[str] = None
    bol_reference: Optional[str] = None
    delivery_date: Optional[str] = None
    items: List[OCRItemResult] = []
    confidence: float = 0.0
