from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class TokenUser(BaseModel):
    user_id: int
    full_name: str
    roles: List[str]
    preferred_language: str
    effective_privileges: List[str] = []


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: TokenUser


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    username: str = Field(..., max_length=50)
    full_name: str = Field(..., max_length=150)
    password: str
    preferred_language: Literal["en", "es"] = "en"
    role_ids: List[int]


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=150)
    preferred_language: Optional[Literal["en", "es"]] = None
    status: Optional[Literal["active", "inactive"]] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    roles: List[str] = []
    preferred_language: str
    status: str
    created_at: datetime


class PaginatedUsers(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[UserResponse]


# ---------------------------------------------------------------------------
# Delivery / Receiving
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

class InventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_type: str
    category: str
    quantity_on_hand: float
    lot_batch_number: str
    storage_location: str
    source_delivery_item_id: Optional[int] = None
    last_updated: datetime
    is_triggered: bool = False


class InventoryListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[InventoryResponse]


class InventoryAdjust(BaseModel):
    quantity_on_hand: float = Field(..., ge=0)
    reason: str


class InventoryAdjustResponse(BaseModel):
    id: int
    quantity_on_hand: float
    last_updated: datetime


class LowStockAlertCreate(BaseModel):
    material_type: str = Field(..., max_length=200)
    threshold: float = Field(..., ge=0)


class LowStockAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_type: str
    threshold: float
    current_quantity: float = 0.0
    is_triggered: bool = False


class LowStockAlertListResponse(BaseModel):
    alerts: List[LowStockAlertResponse]


class TraceabilityResponse(BaseModel):
    lot_batch_number: str
    source_delivery: Optional[Dict[str, Any]] = None
    inventory_items: List[Dict[str, Any]] = []
    work_orders: List[Dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Work Orders
# ---------------------------------------------------------------------------

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


class WorkOrderMaterialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    material_type: str
    quantity_required: float
    quantity_allocated: float


class WorkOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
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
    status: str
    material_availability: List[MaterialAvailability] = []


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------

class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: Optional[int] = None
    action: str
    entity_type: str
    entity_id: Optional[int] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: datetime


class PaginatedAuditLogs(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[AuditLogResponse]
