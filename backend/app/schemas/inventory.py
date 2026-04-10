from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Lot schemas ───────────────────────────────────────────────────────────────

class InventoryLotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: Optional[int] = None
    product_name: Optional[str] = None   # denormalized for display
    lot_number: Optional[str] = None
    storage_location: Optional[str] = None
    status: str
    quantity_on_hand: int                # integer ×100
    source_delivery_item_id: Optional[int] = None
    pallet_number: Optional[int] = None
    is_triggered: bool = False


class InventoryLotListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[InventoryLotResponse]


# ── Transaction schemas ───────────────────────────────────────────────────────

class InventoryTransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    lot_id: int
    transaction_type: str
    quantity: int                        # integer ×100; positive = in, negative = out
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    reason: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime


# ── Adjust / location / split ─────────────────────────────────────────────────

class InventoryAdjust(BaseModel):
    delta: int = Field(..., description="Signed integer ×100 — positive to add, negative to deduct")
    reason: str = Field(..., min_length=1)


class InventoryAdjustResponse(BaseModel):
    id: int
    quantity_on_hand: int                # integer ×100


class LocationUpdate(BaseModel):
    storage_location: str = Field(..., max_length=100)


class LotSplit(BaseModel):
    split_quantity: int = Field(..., gt=0, description="Quantity to split off (integer ×100)")
    storage_location: Optional[str] = Field(None, max_length=100)


class LotSplitResponse(BaseModel):
    source_lot: InventoryAdjustResponse
    new_lot_id: int
    new_lot_quantity: int


# ── Low-stock alert schemas ───────────────────────────────────────────────────

class LowStockAlertCreate(BaseModel):
    product_id: int
    threshold: int = Field(..., ge=0, description="Low-stock threshold (integer ×100)")


class LowStockAlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: Optional[int] = None
    product_name: Optional[str] = None  # denormalized
    threshold: int                       # integer ×100
    current_quantity: int = 0            # integer ×100
    is_triggered: bool = False


class LowStockAlertListResponse(BaseModel):
    alerts: List[LowStockAlertResponse]


# ── Traceability ──────────────────────────────────────────────────────────────

class TraceabilityResponse(BaseModel):
    lot_number: str
    source_delivery: Optional[Dict[str, Any]] = None
    lots: List[Dict[str, Any]] = []
    work_orders: List[Dict[str, Any]] = []


# ── Legacy aliases kept for backward compatibility ────────────────────────────

InventoryResponse = InventoryLotResponse
InventoryListResponse = InventoryLotListResponse
