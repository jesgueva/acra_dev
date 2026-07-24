"""Request/response contracts for the production-worksheet close surface (ACR-30).

Quantities are integers ×100 throughout, matching the ledger convention established by ACR-23
(`150` on the wire means `1.50` units).
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WorksheetLineCreate(BaseModel):
    product_id: int
    planned_quantity: int = Field(..., gt=0)  # ×100


class WorksheetCreate(BaseModel):
    work_order_id: Optional[int] = None
    production_line: Optional[str] = Field(default=None, max_length=100)
    scheduled_date: Optional[str] = Field(default=None, max_length=20)
    lines: List[WorksheetLineCreate] = Field(..., min_length=1)


class WorksheetCloseLine(BaseModel):
    line_id: int
    actual_quantity: int = Field(..., ge=0)  # ×100; 0 is legal — the line consumed nothing


class WorksheetCloseRequest(BaseModel):
    """`expected_version` is the optimistic guard the caller last read on the worksheet."""

    expected_version: int = Field(..., ge=0)
    lines: List[WorksheetCloseLine] = Field(..., min_length=1)


class WorksheetLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    worksheet_id: int
    product_id: int
    product_name: Optional[str] = None  # denormalized
    planned_quantity: int               # ×100
    actual_quantity: Optional[int] = None  # ×100, set at close


class WorksheetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_order_id: Optional[int] = None
    production_line: Optional[str] = None
    scheduled_date: Optional[str] = None
    status: str
    version: int
    created_by: Optional[int] = None
    created_at: datetime
    closed_at: Optional[datetime] = None
    lines: List[WorksheetLineResponse] = []
