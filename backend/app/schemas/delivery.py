from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Item schemas ──────────────────────────────────────────────────────────────

class DeliveryItemBase(BaseModel):
    item_name: str = Field(..., max_length=200)
    description: Optional[str] = None
    quantity: float = Field(..., gt=0)
    pallets: Optional[int] = None
    units_per_pallet: Optional[int] = None


class DeliveryItemCreate(DeliveryItemBase):
    pass


class DeliveryItemResponse(DeliveryItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    leftover: Optional[float] = None
    inventory_item_id: Optional[int] = None


# ── Delivery schemas ──────────────────────────────────────────────────────────

class DeliveryBase(BaseModel):
    supplier: str = Field(..., max_length=200)
    carrier: str = Field(..., max_length=200)
    bol_reference: str = Field(..., max_length=100)
    delivery_date: str = Field(..., max_length=20)
    notes: Optional[str] = None


class DeliveryCreate(DeliveryBase):
    force: bool = False
    items: List[DeliveryItemCreate] = Field(..., min_length=1)


class DeliveryResponse(DeliveryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
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
