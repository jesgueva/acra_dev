from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


#: §4.3 — the two outbound delivery-note flavours. These are the `delivery_notes.type` values;
#: the shipment no longer stores a type of its own.
SHIPMENT_TYPES = ("transfer", "direct_customer")


class ShipmentCreate(BaseModel):
    contact_id: Optional[int] = None      # client contact
    carrier_id: Optional[int] = None
    bol_number: str = Field(..., min_length=1, max_length=100)
    shipment_date: str = Field(..., min_length=1, max_length=20)
    notes: Optional[str] = None
    type: str = Field(default="direct_customer")
    # §4.3 — originating stock location, e.g. "SC". Direct-customer shipments only.
    source: Optional[str] = Field(None, max_length=50)
    items: List[ShipmentItemCreate] = Field(..., min_length=1)

    @field_validator("bol_number", "shipment_date", "source")
    @classmethod
    def _not_blank(cls, v: Optional[str]) -> Optional[str]:
        """Whitespace-only is not a value; an empty `source` normalizes to None."""
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None

    @model_validator(mode="after")
    def _check(self) -> "ShipmentCreate":
        for name in ("bol_number", "shipment_date"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be blank")
        if self.type not in SHIPMENT_TYPES:
            raise ValueError(f"type must be one of {', '.join(SHIPMENT_TYPES)}")
        if self.source is not None and self.type != "direct_customer":
            raise ValueError("source is only valid on a direct_customer shipment")
        return self


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    delivery_note_id: Optional[int] = None
    # `contact_id`, `bol_number`, `shipment_date`, `type` and `source` are projected from the
    # linked delivery note, their only storage location since migration 011.
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
