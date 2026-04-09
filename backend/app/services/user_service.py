from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.security import hash_password, verify_password
from app.models.user import Role, User, UserRoleAssignment
from app.schemas.auth import TokenUser
from app.schemas.user import PaginatedUsers, UserCreate, UserResponse, UserUpdate


async def _get_user_roles(db: AsyncSession, user_id: int) -> List[str]:
    result = await db.execute(
        select(Role.role_name)
        .join(UserRoleAssignment, Role.id == UserRoleAssignment.role_id)
        .where(UserRoleAssignment.user_id == user_id)
    )
    return [r[0] for r in result.fetchall()]


async def _user_to_response(db: AsyncSession, user: User) -> UserResponse:
    roles = await _get_user_roles(db, user.id)
    return UserResponse(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        roles=roles,
        preferred_language=user.preferred_language,
        status=user.status,
        created_at=user.created_at,
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

    results = [await _user_to_response(db, u) for u in users]
    return PaginatedUsers(total=total, page=page, page_size=page_size, results=results)


async def get_user(db: AsyncSession, user_id: int) -> UserResponse:
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await _user_to_response(db, user)


async def create_user(db: AsyncSession, data: UserCreate, actor_id: int) -> UserResponse:
    existing = (
        await db.execute(select(User).where(User.username == data.username))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

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
        role = (
            await db.execute(select(Role).where(Role.id == role_id))
        ).scalar_one_or_none()
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Role {role_id} not found",
            )
        db.add(UserRoleAssignment(user_id=user.id, role_id=role_id))

    await write_audit(db, actor_id, "create_user", "user", user.id, {"username": data.username})
    await db.commit()
    await db.refresh(user)
    return await _user_to_response(db, user)


async def update_user(
    db: AsyncSession, user_id: int, data: UserUpdate, actor_id: int
) -> UserResponse:
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

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
    return await _user_to_response(db, user)


async def update_me(db: AsyncSession, user_id: int, preferred_language: str) -> UserResponse:
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.preferred_language = preferred_language
    await db.commit()
    await db.refresh(user)
    return await _user_to_response(db, user)


async def change_password(
    db: AsyncSession,
    user_id: int,
    current_password: Optional[str],
    new_password: str,
    actor: TokenUser,
) -> dict:
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

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
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await db.execute(delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user_id))

    for role_id in role_ids:
        role = (
            await db.execute(select(Role).where(Role.id == role_id))
        ).scalar_one_or_none()
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Role {role_id} not found",
            )
        db.add(UserRoleAssignment(user_id=user_id, role_id=role_id))

    await write_audit(db, actor_id, "replace_roles", "user", user_id)
    await db.commit()
    await db.refresh(user)
    return await _user_to_response(db, user)
