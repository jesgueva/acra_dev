from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import Role
from app.schemas.role import RoleList, RoleResponse


async def list_roles(db: AsyncSession) -> RoleList:
    """Return every role, ordered by id.

    The set is small and fixed by migration 001, so this is deliberately
    unpaginated — the User Management form needs all of them to map a
    selected role back to the `role_ids` that POST /users expects.
    """
    roles = (await db.execute(select(Role).order_by(Role.id))).scalars().all()
    return RoleList(results=[RoleResponse.model_validate(r) for r in roles])
