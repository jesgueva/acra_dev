from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.production_worksheet import (
    WorksheetCloseRequest,
    WorksheetCreate,
    WorksheetResponse,
)
from app.services import production_worksheet_service

router = APIRouter(prefix="/api/v1/production-worksheets", tags=["production-worksheets"])


@router.post("", response_model=WorksheetResponse, status_code=status.HTTP_201_CREATED)
async def create_worksheet(
    body: WorksheetCreate,
    current_user: TokenUser = Depends(require_privilege("production.worksheet.create")),
    db: AsyncSession = Depends(get_db),
) -> WorksheetResponse:
    return await production_worksheet_service.create_worksheet(
        db=db, body=body, current_user=current_user
    )


@router.get("/{worksheet_id}", response_model=WorksheetResponse)
async def get_worksheet(
    worksheet_id: int,
    current_user: TokenUser = Depends(require_privilege("production.worksheet.view")),
    db: AsyncSession = Depends(get_db),
) -> WorksheetResponse:
    return await production_worksheet_service.get_worksheet(db=db, worksheet_id=worksheet_id)


@router.post("/{worksheet_id}/close", response_model=WorksheetResponse)
async def close_worksheet(
    worksheet_id: int,
    body: WorksheetCloseRequest,
    current_user: TokenUser = Depends(require_privilege("production.worksheet.close")),
    db: AsyncSession = Depends(get_db),
) -> WorksheetResponse:
    return await production_worksheet_service.close_worksheet(
        db=db, worksheet_id=worksheet_id, body=body, current_user=current_user
    )
