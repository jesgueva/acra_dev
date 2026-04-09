from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DeliveryItemCreate(BaseModel):
    material_type: str = Field(..., max_length=200)
    quantity: float = Field(..., gt=0)
    lot_batch_number: str = Field(..., max_length=100)
    storage_location: str = Field(..., max_length=100)


class DeliveryCreate(BaseModel):
    supplier: str = Field(..., max_length=200)
    carrier: str = Field(..., max_length=200)
    delivery_date: date
    bol_reference: str = Field(..., max_length=100)
    items: List[DeliveryItemCreate] = Field(..., min_length=1)
    force: bool = False


class DeliveryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_type: str
    quantity: float
    lot_batch_number: str
    storage_location: str
    inventory_item_id: Optional[int] = None


class DeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier: str
    carrier: str
    delivery_date: date
    bol_reference: str
    created_by: int
    created_at: datetime
    items: List[DeliveryItemResponse] = []


class DeliveryListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[DeliveryResponse]


class OCRItemResult(BaseModel):
    material_type: Optional[str] = None
    quantity: Optional[float] = None
    lot_batch_number: Optional[str] = None


class OCRResponse(BaseModel):
    supplier: Optional[str] = None
    carrier: Optional[str] = None
    bol_reference: Optional[str] = None
    delivery_date: Optional[str] = None
    items: List[OCRItemResult] = []
    confidence: float = 0.0
