from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import LoginRequest, LoginResponse, TokenUser
from app.services import auth as auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    return await auth_service.login(body.username, body.password, db)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    current_user: TokenUser = Depends(require_privilege("authenticated")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await auth_service.logout(current_user.user_id, db)
    return {"detail": "Logged out successfully"}
