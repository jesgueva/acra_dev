from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_any_privilege, require_privilege
from app.schemas.auth import TokenUser
from app.schemas.contact import ContactCreate, ContactListResponse, ContactResponse, ContactUpdate
from app.services import contact_service

router = APIRouter(prefix="/api/v1/contacts", tags=["contacts"])


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    type: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    current_user: TokenUser = Depends(require_any_privilege("master_data.view", "deliveries.create")),
    db: AsyncSession = Depends(get_db),
) -> ContactListResponse:
    return await contact_service.list_contacts(
        db=db, page=page, page_size=page_size, type_filter=type, name=name
    )


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_id: int,
    current_user: TokenUser = Depends(require_privilege("master_data.view")),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    return await contact_service.get_contact(db=db, contact_id=contact_id)


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    body: ContactCreate,
    current_user: TokenUser = Depends(require_privilege("master_data.manage")),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    return await contact_service.create_contact(db=db, data=body)


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: int,
    body: ContactUpdate,
    current_user: TokenUser = Depends(require_privilege("master_data.manage")),
    db: AsyncSession = Depends(get_db),
) -> ContactResponse:
    return await contact_service.update_contact(db=db, contact_id=contact_id, data=body)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: int,
    current_user: TokenUser = Depends(require_privilege("master_data.manage")),
    db: AsyncSession = Depends(get_db),
) -> None:
    await contact_service.delete_contact(db=db, contact_id=contact_id)
