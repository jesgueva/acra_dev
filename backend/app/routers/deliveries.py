from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.delivery import DeliveryCreate, DeliveryListResponse, DeliveryResponse, OCRResponse
from app.services import delivery_service, ocr_service

router = APIRouter(prefix="/api/v1/deliveries", tags=["deliveries"])

_OCR_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
_OCR_ALLOWED_TYPES = {"image/jpeg", "image/png", "application/pdf"}


@router.post("/ocr", response_model=OCRResponse)
async def ocr_delivery(
    request: Request,
    file: UploadFile = File(...),
    current_user: TokenUser = Depends(require_privilege("deliveries.create")),
) -> OCRResponse:
    """Extract BOL fields from an uploaded image or PDF using OCR."""
    if file.content_type not in _OCR_ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported file type. Use JPEG, PNG, or PDF.",
        )
    cl = request.headers.get("content-length")
    if cl and int(cl) > _OCR_MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File exceeds maximum size of 10 MB.",
        )
    content = await file.read()
    if len(content) > _OCR_MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File exceeds maximum size of 10 MB.",
        )
    result = ocr_service.process_image_bytes(content, file.content_type)
    if result.confidence == 0.0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unable to extract data. Please enter manually.",
        )
    return result


@router.post("", response_model=DeliveryResponse, status_code=status.HTTP_201_CREATED)
async def create_delivery(
    body: DeliveryCreate,
    current_user: TokenUser = Depends(require_privilege("deliveries.create")),
    db: AsyncSession = Depends(get_db),
) -> DeliveryResponse:
    return await delivery_service.create_delivery(body, current_user, db)


@router.get("", response_model=DeliveryListResponse)
async def list_deliveries(
    supplier: Optional[str] = Query(None),
    carrier: Optional[str] = Query(None),
    bol_reference: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: TokenUser = Depends(require_privilege("deliveries.view")),
    db: AsyncSession = Depends(get_db),
) -> DeliveryListResponse:
    return await delivery_service.list_deliveries(
        db=db,
        supplier=supplier,
        carrier=carrier,
        bol_reference=bol_reference,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
