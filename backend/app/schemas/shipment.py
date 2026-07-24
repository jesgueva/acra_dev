from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.shipment import SHIPMENT_TYPE_DIRECT_CUSTOMER

# Domain model §4.3 — Transfer note vs Direct Customer note.
ShipmentType = Literal["transfer", "direct_customer"]


class ShipmentItemCreate(BaseModel):
    lot_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)                    # integer ×100
    unit_price: Optional[int] = Field(None, ge=0)       # integer ×100, price snapshot


class ShipmentItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int
    lot_id: int
    quantity: int                          # ×100
    unit_price: Optional[int] = None       # ×100
    product_name: Optional[str] = None    # denormalized
    lot_number: Optional[str] = None      # denormalized


class ShipmentCreate(BaseModel):
    contact_id: Optional[int] = None      # client contact
    carrier_id: Optional[int] = None
    bol_number: str = Field(..., min_length=1, max_length=100)
    shipment_date: str = Field(..., min_length=1, max_length=20)
    notes: Optional[str] = None
    type: ShipmentType = SHIPMENT_TYPE_DIRECT_CUSTOMER
    # §4.3 — originating stock location, e.g. "SC". Direct Customer notes only.
    source: Optional[str] = Field(None, max_length=50)
    items: List[ShipmentItemCreate] = Field(..., min_length=1)

    @field_validator("bol_number", "shipment_date", "source")
    @classmethod
    def _reject_blank(cls, v: Optional[str]) -> Optional[str]:
        """Whitespace-only is not a value. Empty `source` normalizes to None."""
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @model_validator(mode="after")
    def _source_is_direct_customer_only(self) -> "ShipmentCreate":
        if self.source is not None and self.type != SHIPMENT_TYPE_DIRECT_CUSTOMER:
            raise ValueError("source is only valid on a direct_customer shipment")
        return self


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
    source: Optional[str] = None
    created_by: int
    created_at: datetime
    items: List[ShipmentItemResponse] = []


class ShipmentListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[ShipmentResponse]
