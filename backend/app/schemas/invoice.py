from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class InvoiceLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    shipment_item_id: int
    description: str
    quantity: int      # ×100
    unit_price: int    # ×100
    line_total: int    # ×100


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    shipment_id: int
    invoice_number: str
    invoice_date: str
    currency: str
    subtotal_amount: int   # ×100
    tax_amount: int        # ×100
    total_amount: int      # ×100
    status: str
    created_by: int
    created_at: datetime
    bol_number: Optional[str] = None    # denormalized
    contact_name: Optional[str] = None  # denormalized
    lines: List[InvoiceLineResponse] = []
