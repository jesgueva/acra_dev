"""
Create (or reset) the built-in admin user and admin role.

Usage:
    python scripts/create_admin.py

Idempotent — safe to run multiple times.
"""
import asyncio
import os
import sys

# Allow running from the backend/ root or from scripts/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_password
from app.models.user import Role, RolePrivilegeAssignment, User, UserRoleAssignment

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db",
)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
ADMIN_FULL_NAME = "Administrator"
ADMIN_ROLE = "admin"

ALL_PRIVILEGES = [
    "inventory.view",
    "inventory.edit",
    "work_order.view",
    "work_order.edit",
    "delivery.view",
    "delivery.edit",
    "audit.view",
    "admin",
]


async def create_admin() -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        # Ensure admin role exists
        result = await db.execute(select(Role).where(Role.role_name == ADMIN_ROLE))
        role = result.scalar_one_or_none()
        if role is None:
            role = Role(role_name=ADMIN_ROLE, description="Full system access")
            db.add(role)
            await db.flush()
            print(f"Created role '{ADMIN_ROLE}'")
        else:
            print(f"Role '{ADMIN_ROLE}' already exists (id={role.id})")

        # Ensure all privileges are assigned to admin role
        for priv in ALL_PRIVILEGES:
            exists = await db.execute(
                select(RolePrivilegeAssignment).where(
                    RolePrivilegeAssignment.role_id == role.id,
                    RolePrivilegeAssignment.privilege_name == priv,
                )
            )
            if exists.scalar_one_or_none() is None:
                db.add(RolePrivilegeAssignment(role_id=role.id, privilege_name=priv))

        # Ensure admin user exists
        result = await db.execute(select(User).where(User.username == ADMIN_USERNAME))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                username=ADMIN_USERNAME,
                password_hash=hash_password(ADMIN_PASSWORD),
                full_name=ADMIN_FULL_NAME,
                preferred_language="en",
                status="active",
            )
            db.add(user)
            await db.flush()
            print(f"Created user '{ADMIN_USERNAME}' (id={user.id})")
        else:
            # Reset password in case it was changed
            user.password_hash = hash_password(ADMIN_PASSWORD)
            user.status = "active"
            print(f"User '{ADMIN_USERNAME}' already exists (id={user.id}) — password reset")

        # Ensure admin user has admin role
        assignment = await db.execute(
            select(UserRoleAssignment).where(
                UserRoleAssignment.user_id == user.id,
                UserRoleAssignment.role_id == role.id,
            )
        )
        if assignment.scalar_one_or_none() is None:
            db.add(UserRoleAssignment(user_id=user.id, role_id=role.id))
            print(f"Assigned role '{ADMIN_ROLE}' to user '{ADMIN_USERNAME}'")

        await db.commit()
        print("Done — admin user ready.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_admin())
