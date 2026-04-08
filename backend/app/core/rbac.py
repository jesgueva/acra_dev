from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_token
from app.schemas.auth import TokenUser

# Hardcoded privilege map — no role_privilege_assignments table in schema
ROLE_PRIVILEGES: dict[str, list[str]] = {
    "company_admin": [
        "users.manage",
        "audit.view",
        "deliveries.create",
        "deliveries.view",
        "inventory.view",
        "inventory.adjust",
        "inventory.alerts.manage",
        "work_orders.create",
        "work_orders.view",
        "work_orders.assign",
        "work_orders.status_update",
        "work_orders.sequence",
        "work_orders.allocate",
    ],
    "receiving_clerk": [
        "deliveries.create",
        "deliveries.view",
        "inventory.view",
    ],
    "production_supervisor": [
        "deliveries.view",
        "inventory.view",
        "work_orders.create",
        "work_orders.view",
        "work_orders.assign",
        "work_orders.status_update",
        "work_orders.sequence",
        "work_orders.allocate",
    ],
    "machine_operator": [
        "work_orders.view",
    ],
}

_bearer = HTTPBearer()


def require_privilege(privilege: str):
    """
    FastAPI dependency factory.

    Usage:
        current_user: TokenUser = Depends(require_privilege("inventory.view"))

    Special value "authenticated" skips privilege check — just validates the JWT.
    """

    async def _dependency(
        credentials: HTTPAuthorizationCredentials = Depends(_bearer),
        db: AsyncSession = Depends(get_db),
    ) -> TokenUser:
        token = credentials.credentials
        try:
            user_id = verify_token(token)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        from app.models.user import Role, User, UserRoleAssignment  # avoid circular

        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if user is None or user.status != "active":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or inactive",
                headers={"WWW-Authenticate": "Bearer"},
            )

        roles_result = await db.execute(
            select(Role.role_name)
            .join(UserRoleAssignment, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.user_id == user_id)
        )
        role_names: list[str] = [r[0] for r in roles_result.fetchall()]

        effective_privileges: list[str] = list(
            {p for role in role_names for p in ROLE_PRIVILEGES.get(role, [])}
        )

        token_user = TokenUser(
            user_id=user.id,
            full_name=user.full_name,
            roles=role_names,
            preferred_language=user.preferred_language,
            effective_privileges=effective_privileges,
        )

        if privilege == "authenticated":
            return token_user

        if privilege not in effective_privileges:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required privilege: {privilege}",
            )

        return token_user

    return _dependency
