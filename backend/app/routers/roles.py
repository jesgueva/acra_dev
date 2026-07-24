from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rbac import require_privilege
from app.schemas.auth import TokenUser
from app.schemas.role import RoleList
from app.services import role_service

router = APIRouter(prefix="/api/v1/roles", tags=["roles"])


@router.get("", response_model=RoleList)
async def list_roles(
    current_user: TokenUser = Depends(require_privilege("users.manage")),
    db: AsyncSession = Depends(get_db),
) -> RoleList:
    return await role_service.list_roles(db)
