from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class InventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_name: str
    category: str
    quantity_on_hand: float
    lot_batch_number: Optional[str] = None
    storage_location: Optional[str] = None
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
    item_name: str = Field(..., max_length=200)
    threshold: float = Field(..., ge=0)


class LowStockAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_name: str
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
