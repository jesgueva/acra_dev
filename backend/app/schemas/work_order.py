from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class WorkOrderMaterialCreate(BaseModel):
    material_type: str = Field(..., max_length=200)
    quantity_required: float = Field(..., gt=0)


class WorkOrderCreate(BaseModel):
    product: str = Field(..., max_length=200)
    quantity_required: float = Field(..., gt=0)
    priority: Literal["low", "medium", "high", "urgent"] = "medium"
    target_date: date
    production_line: Optional[str] = Field(None, max_length=50)
    materials: List[WorkOrderMaterialCreate] = Field(..., min_length=1)


class WorkOrderAssign(BaseModel):
    production_line: str = Field(..., max_length=50)


class WorkOrderStatusUpdate(BaseModel):
    status: Literal[
        "materials_allocated", "in_production", "completed", "ready_for_shipment"
    ]
    quantity_produced: Optional[float] = Field(None, ge=0)


class WorkOrderSequenceUpdate(BaseModel):
    display_sequence: int = Field(..., ge=0)


class WorkOrderMaterialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_type: str
    quantity_required: float
    quantity_allocated: float


class WorkOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    wo_number: str
    product: str
    status: str
    priority: str
    display_sequence: int
    production_line: Optional[str] = None
    target_date: date
    quantity_required: float
    quantity_produced: float
    created_by: int
    created_at: datetime
    updated_at: datetime
    materials: List[WorkOrderMaterialResponse] = []


class WorkOrderAssignResponse(WorkOrderResponse):
    capacity_warning: Optional[str] = None


class WorkOrderListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[WorkOrderResponse]


class MaterialAvailability(BaseModel):
    material_type: str
    required: float
    available: float
    sufficient: bool


class WorkOrderCreateResponse(BaseModel):
    id: int
    wo_number: str
    status: str
    material_availability: List[MaterialAvailability] = []
