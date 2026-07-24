from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.delivery_note import DeliveryNoteType


class DeliveryNoteBase(BaseModel):
    type: DeliveryNoteType
    source: Optional[str] = Field(None, max_length=50)
    partner_id: Optional[int] = None
    document_number: str = Field(..., min_length=1, max_length=100)
    document_date: str = Field(..., min_length=1, max_length=20)
    uploaded: bool = False
    notes: Optional[str] = None

    @field_validator("document_number", "document_date", "source")
    @classmethod
    def _not_blank(cls, v: Optional[str]) -> Optional[str]:
        """Whitespace-only is not a value; an empty `source` normalizes to None."""
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None

    @model_validator(mode="after")
    def _check_required_and_source_scope(self) -> "DeliveryNoteBase":
        # `_not_blank` turns "   " into None, which Field(min_length=1) no longer catches.
        for name in ("document_number", "document_date"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be blank")
        # §4.3 — `source` names the originating stock location, and only a direct-customer
        # note has one. Mirrors ck_delivery_notes_source_direct_only.
        if self.source is not None and self.type != DeliveryNoteType.DIRECT_CUSTOMER:
            raise ValueError("source is only valid on a direct_customer delivery note")
        return self


class DeliveryNoteResponse(DeliveryNoteBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    partner_name: Optional[str] = None    # denormalized
    created_by: int
    created_at: datetime


class DeliveryNoteListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[DeliveryNoteResponse]
