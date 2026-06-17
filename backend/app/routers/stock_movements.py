"""Phase 2 — stock-movement ledger router (skeleton placeholder).

Reserves the C-04 ledger surface in the live API so the skeleton is aligned with the design
review. Every route returns **501 Not Implemented** until the ledger lands in Sprint II. Kept
dependency-free (no DB/RBAC) so the placeholder can never fail to import or respond.
"""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/v1/stock-movements", tags=["stock-movements (Phase 2)"])

_DETAIL = "Not implemented — the StockMovement ledger lands in Sprint II (Phase 2)."


@router.get("", summary="List stock movements (Phase 2 — not implemented)")
async def list_stock_movements() -> JSONResponse:
    """Placeholder for the ledger read surface. Returns 501 until Sprint II."""
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={"detail": _DETAIL},
    )
