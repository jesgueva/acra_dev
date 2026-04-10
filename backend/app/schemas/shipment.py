from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ShipmentItemCreate(BaseModel):
    lot_id: int
    quantity: int = Field(..., gt=0)  # integer ×100


class ShipmentItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int
    lot_id: int
    quantity: int                          # ×100
    product_name: Optional[str] = None    # denormalized
    lot_number: Optional[str] = None      # denormalized


class ShipmentCreate(BaseModel):
    contact_id: Optional[int] = None      # client contact
    carrier_id: Optional[int] = None
    bol_number: str = Field(..., max_length=100)
    shipment_date: str = Field(..., max_length=20)
    notes: Optional[str] = None
    type: str = Field(default="customer_order")
    items: List[ShipmentItemCreate] = Field(..., min_length=1)


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contact_id: Optional[int] = None
    contact_name: Optional[str] = None    # denormalized
    carrier_id: Optional[int] = None
    carrier_name: Optional[str] = None    # denormalized
    bol_number: str
    shipment_date: str
    notes: Optional[str] = None
    type: str
    created_by: int
    created_at: datetime
    items: List[ShipmentItemResponse] = []


class ShipmentListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[ShipmentResponse]
