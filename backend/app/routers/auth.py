from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.database import get_db
from app.core.rbac import require_privilege
from app.core.security import create_access_token, verify_password
from app.models.user import Role, RolePrivilegeAssignment, User, UserRoleAssignment
from app.schemas.auth import LoginRequest, LoginResponse, TokenUser

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if user.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    roles_result = await db.execute(
        select(Role.role_name)
        .join(UserRoleAssignment, Role.id == UserRoleAssignment.role_id)
        .where(UserRoleAssignment.user_id == user.id)
    )
    role_names: list[str] = [r[0] for r in roles_result.fetchall()]

    privs_result = await db.execute(
        select(RolePrivilegeAssignment.privilege_name)
        .join(UserRoleAssignment, RolePrivilegeAssignment.role_id == UserRoleAssignment.role_id)
        .where(UserRoleAssignment.user_id == user.id)
        .distinct()
    )
    effective_privileges: list[str] = [r[0] for r in privs_result.fetchall()]

    access_token = create_access_token(user_id=user.id)

    await write_audit(
        db=db,
        user_id=user.id,
        action="login",
        entity_type="user",
        entity_id=user.id,
    )
    await db.commit()

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=TokenUser(
            user_id=user.id,
            full_name=user.full_name,
            roles=role_names,
            preferred_language=user.preferred_language,
            effective_privileges=effective_privileges,
        ),
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    current_user: TokenUser = Depends(require_privilege("authenticated")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await write_audit(
        db=db,
        user_id=current_user.user_id,
        action="logout",
        entity_type="user",
        entity_id=current_user.user_id,
    )
    await db.commit()
    return {"detail": "Logged out successfully"}
