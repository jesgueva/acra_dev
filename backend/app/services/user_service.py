from typing import Dict, List, Optional, Set

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.security import hash_password, verify_password
from app.models.user import Role, User, UserRoleAssignment
from app.schemas.auth import TokenUser
from app.schemas.user import PaginatedUsers, UserCreate, UserResponse, UserUpdate


async def _get_user_or_404(db: AsyncSession, user_id: int) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _fetch_roles_for_users(db: AsyncSession, user_ids: List[int]) -> Dict[int, List[str]]:
    """Fetch roles for multiple users in a single query — avoids N+1."""
    rows = (
        await db.execute(
            select(UserRoleAssignment.user_id, Role.role_name)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(UserRoleAssignment.user_id.in_(user_ids))
        )
    ).fetchall()
    result: Dict[int, List[str]] = {uid: [] for uid in user_ids}
    for uid, role_name in rows:
        result[uid].append(role_name)
    return result


async def _get_user_roles(db: AsyncSession, user_id: int) -> List[str]:
    roles = await _fetch_roles_for_users(db, [user_id])
    return roles[user_id]


def _user_to_response(user: User, roles: List[str]) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        roles=roles,
        preferred_language=user.preferred_language,
        status=user.status,
        created_at=user.created_at,
    )


async def _validate_role_ids(db: AsyncSession, role_ids: List[int]) -> None:
    """Validate all role IDs exist in a single query."""
    if not role_ids:
        return
    found: Set[int] = set(
        (await db.execute(select(Role.id).where(Role.id.in_(role_ids)))).scalars().all()
    )
    missing = set(role_ids) - found
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Roles not found: {sorted(missing)}",
        )


async def list_users(
    db: AsyncSession,
    page: int,
    page_size: int,
    filter_status: Optional[str] = None,
    filter_role: Optional[str] = None,
) -> PaginatedUsers:
    count_q = select(func.count()).select_from(User)
    main_q = select(User)

    if filter_status:
        count_q = count_q.where(User.status == filter_status)
        main_q = main_q.where(User.status == filter_status)

    if filter_role:
        sub = (
            select(UserRoleAssignment.user_id)
            .join(Role, Role.id == UserRoleAssignment.role_id)
            .where(Role.role_name == filter_role)
        )
        count_q = count_q.where(User.id.in_(sub))
        main_q = main_q.where(User.id.in_(sub))

    total = (await db.execute(count_q)).scalar()
    users = (
        await db.execute(main_q.offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()

    if users:
        roles_map = await _fetch_roles_for_users(db, [u.id for u in users])
    else:
        roles_map = {}

    results = [_user_to_response(u, roles_map[u.id]) for u in users]
    return PaginatedUsers(total=total, page=page, page_size=page_size, results=results)


async def get_user(db: AsyncSession, user_id: int) -> UserResponse:
    user = await _get_user_or_404(db, user_id)
    roles = await _get_user_roles(db, user.id)
    return _user_to_response(user, roles)


async def create_user(db: AsyncSession, data: UserCreate, actor_id: int) -> UserResponse:
    existing = (
        await db.execute(select(User).where(User.username == data.username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    await _validate_role_ids(db, data.role_ids)

    user = User(
        username=data.username,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        preferred_language=data.preferred_language,
        status="active",
    )
    db.add(user)
    await db.flush()

    for role_id in data.role_ids:
        db.add(UserRoleAssignment(user_id=user.id, role_id=role_id))

    await write_audit(db, actor_id, "create_user", "user", user.id, {"username": data.username})
    await db.commit()
    await db.refresh(user)
    roles = await _get_user_roles(db, user.id)
    return _user_to_response(user, roles)


async def update_user(
    db: AsyncSession, user_id: int, data: UserUpdate, actor_id: int
) -> UserResponse:
    user = await _get_user_or_404(db, user_id)

    if data.status == "inactive":
        admin_role = (
            await db.execute(select(Role).where(Role.role_name == "company_admin"))
        ).scalar_one_or_none()
        if admin_role is not None:
            admin_count = (
                await db.execute(
                    select(func.count())
                    .select_from(UserRoleAssignment)
                    .join(User, User.id == UserRoleAssignment.user_id)
                    .where(UserRoleAssignment.role_id == admin_role.id)
                    .where(User.status == "active")
                )
            ).scalar()
            user_is_admin = (
                await db.execute(
                    select(UserRoleAssignment)
                    .where(UserRoleAssignment.user_id == user_id)
                    .where(UserRoleAssignment.role_id == admin_role.id)
                )
            ).scalar_one_or_none()
            if user_is_admin is not None and admin_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot deactivate the last admin",
                )

    if data.full_name is not None:
        user.full_name = data.full_name
    if data.preferred_language is not None:
        user.preferred_language = data.preferred_language
    if data.status is not None:
        user.status = data.status

    await write_audit(db, actor_id, "update_user", "user", user_id)
    await db.commit()
    await db.refresh(user)
    roles = await _get_user_roles(db, user.id)
    return _user_to_response(user, roles)


async def update_me(db: AsyncSession, user_id: int, preferred_language: str) -> UserResponse:
    user = await _get_user_or_404(db, user_id)
    user.preferred_language = preferred_language
    await db.commit()
    await db.refresh(user)
    roles = await _get_user_roles(db, user.id)
    return _user_to_response(user, roles)


async def change_password(
    db: AsyncSession,
    user_id: int,
    current_password: Optional[str],
    new_password: str,
    actor: TokenUser,
) -> dict:
    user = await _get_user_or_404(db, user_id)

    is_admin = "users.manage" in actor.effective_privileges
    is_self = actor.user_id == user_id

    if not is_admin and not is_self:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    if not is_admin:
        if current_password is None or not verify_password(current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Wrong current password",
            )

    user.password_hash = hash_password(new_password)
    await write_audit(db, actor.user_id, "change_password", "user", user_id)
    await db.commit()
    return {"detail": "Password changed successfully"}


async def replace_roles(
    db: AsyncSession, user_id: int, role_ids: List[int], actor_id: int
) -> UserResponse:
    user = await _get_user_or_404(db, user_id)

    await _validate_role_ids(db, role_ids)
    await db.execute(delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user_id))

    for role_id in role_ids:
        db.add(UserRoleAssignment(user_id=user_id, role_id=role_id))

    await write_audit(db, actor_id, "replace_roles", "user", user_id)
    await db.commit()
    await db.refresh(user)
    roles = await _get_user_roles(db, user.id)
    return _user_to_response(user, roles)
