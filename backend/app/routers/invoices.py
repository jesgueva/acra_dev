from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.invoice import InvoiceResponse
from app.services import invoice_service

router = APIRouter(prefix="/api/v1/shipments", tags=["invoices"])


@router.post(
    "/{shipment_id}/invoice",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_invoice(
    shipment_id: int,
    current_user: TokenUser = Depends(require_privilege("shipping.create")),
    db: AsyncSession = Depends(get_db),
) -> InvoiceResponse:
    return await invoice_service.generate_invoice(shipment_id, current_user, db)


@router.get("/{shipment_id}/invoice", response_model=InvoiceResponse)
async def get_invoice(
    shipment_id: int,
    current_user: TokenUser = Depends(require_privilege("shipping.view")),
    db: AsyncSession = Depends(get_db),
) -> InvoiceResponse:
    return await invoice_service.get_invoice_for_shipment(shipment_id, db)
