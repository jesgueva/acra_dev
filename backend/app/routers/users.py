from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.user import (
    ChangePasswordRequest,
    PaginatedUsers,
    RolesUpdate,
    SelfLanguageUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from app.services import user_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=PaginatedUsers)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    current_user: TokenUser = Depends(require_privilege("users.manage")),
    db: AsyncSession = Depends(get_db),
) -> PaginatedUsers:
    return await user_service.list_users(db, page, page_size, status, role)


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    current_user: TokenUser = Depends(require_privilege("users.manage")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await user_service.create_user(db, body, current_user.user_id)


@router.get("/me", response_model=TokenUser)
async def get_me(
    current_user: TokenUser = Depends(require_privilege("authenticated")),
) -> TokenUser:
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    body: SelfLanguageUpdate,
    current_user: TokenUser = Depends(require_privilege("authenticated")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await user_service.update_me(db, current_user.user_id, body.preferred_language)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: TokenUser = Depends(require_privilege("users.manage")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await user_service.get_user(db, user_id)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: UserUpdate,
    current_user: TokenUser = Depends(require_privilege("users.manage")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await user_service.update_user(db, user_id, body, current_user.user_id)


@router.post("/{user_id}/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    user_id: int,
    body: ChangePasswordRequest,
    current_user: TokenUser = Depends(require_privilege("authenticated")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await user_service.change_password(
        db, user_id, body.current_password, body.new_password, current_user
    )


@router.post("/{user_id}/roles", response_model=UserResponse)
async def replace_roles(
    user_id: int,
    body: RolesUpdate,
    current_user: TokenUser = Depends(require_privilege("users.manage")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    return await user_service.replace_roles(db, user_id, body.role_ids, current_user.user_id)
