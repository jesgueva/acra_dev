"""`scripts/bootstrap_admin.py` against a real, migrated database.

Requires a running PostgreSQL with migrations applied — same contract as `tests/test_schema.py` and
the other `tests/integration/` modules; skipped when nothing is listening.

Unlike the seed, this cleans up after itself: it creates a uniquely-named user and removes it, its
role assignment and its audit rows afterwards, and deletes exactly the privilege grants the run
added (on a migrated-but-unseeded database, `receiving.view` and the `authenticated` sentinel rows).
"""
import os
import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import verify_password
from app.models.audit import AuditLog
from app.models.user import Role, RolePrivilegeAssignment, User, UserRoleAssignment
from scripts.bootstrap_admin import ADMIN_ROLE, bootstrap_admin
from scripts.seed_fake_data import ROLE_DEFINITIONS
from tests.conftest import skip_if_no_postgres

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/acra_db",
)


async def _grants(db: AsyncSession) -> set[tuple[int, str]]:
    rows = await db.execute(
        select(RolePrivilegeAssignment.role_id, RolePrivilegeAssignment.privilege_name)
    )
    return {(role_id, privilege) for role_id, privilege in rows}


@pytest.fixture
async def sessions():
    """(sessionmaker, unique username). Yields the maker, not a session — see
    `tests/integration/test_seed_scaling.py` for the event-loop reason."""
    await skip_if_no_postgres()
    engine = create_async_engine(DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        grants_before = await _grants(db)
    username = f"it-bootstrap-{uuid.uuid4().hex[:12]}"

    yield maker, username

    async with maker() as db:
        user_id = (
            await db.execute(select(User.id).where(User.username == username))
        ).scalar_one_or_none()
        if user_id is not None:
            await db.execute(
                delete(AuditLog).where(
                    AuditLog.entity_type == "user", AuditLog.entity_id == user_id
                )
            )
            await db.execute(
                delete(UserRoleAssignment).where(UserRoleAssignment.user_id == user_id)
            )
            await db.execute(delete(User).where(User.id == user_id))
        for role_id, privilege in await _grants(db) - grants_before:
            await db.execute(
                delete(RolePrivilegeAssignment).where(
                    RolePrivilegeAssignment.role_id == role_id,
                    RolePrivilegeAssignment.privilege_name == privilege,
                )
            )
        await db.commit()
    await engine.dispose()


async def _user(db: AsyncSession, username: str) -> User:
    return (await db.execute(select(User).where(User.username == username))).scalar_one()


async def test_creates_an_active_company_admin_holding_every_seed_privilege(sessions):
    maker, username = sessions
    async with maker() as db:
        assert await bootstrap_admin(db, username=username, password="first-password-123") is True
        await db.commit()

    async with maker() as db:
        user = await _user(db, username)
        profile = (user.status, user.full_name, user.preferred_language)
        assert profile == ("active", "Administrator", "en")
        assert verify_password("first-password-123", user.password_hash)

        roles = await db.execute(
            select(Role.role_name)
            .join(UserRoleAssignment, UserRoleAssignment.role_id == Role.id)
            .where(UserRoleAssignment.user_id == user.id)
        )
        assert roles.scalars().all() == [ADMIN_ROLE]

        # Every role, not just company_admin: a clerk created later through the Users page needs
        # receiving.view too, and no migration grants it.
        for role_name, definition in ROLE_DEFINITIONS.items():
            granted = await db.execute(
                select(RolePrivilegeAssignment.privilege_name)
                .join(Role, Role.id == RolePrivilegeAssignment.role_id)
                .where(Role.role_name == role_name)
            )
            missing = set(definition["privileges"]) - set(granted.scalars())
            assert not missing, f"{role_name} lacks {sorted(missing)} after bootstrap"

        audit = await db.execute(
            select(AuditLog.action, AuditLog.user_id).where(
                AuditLog.entity_type == "user", AuditLog.entity_id == user.id
            )
        )
        assert audit.all() == [("create_user", None)]


async def test_rerun_resets_the_password_but_keeps_the_profile_and_one_role(sessions):
    maker, username = sessions
    async with maker() as db:
        await bootstrap_admin(
            db,
            username=username,
            password="first-password-123",
            full_name="Jane Doe",
            preferred_language="es",
        )
        await db.commit()
    async with maker() as db:
        user = await _user(db, username)
        user.status = "inactive"  # the locked-out case the reset exists for
        await db.commit()

    async with maker() as db:
        assert await bootstrap_admin(db, username=username, password="second-password-456") is False
        await db.commit()

    async with maker() as db:
        user = await _user(db, username)
        assert verify_password("second-password-456", user.password_hash)
        assert not verify_password("first-password-123", user.password_hash)
        profile = (user.status, user.full_name, user.preferred_language)
        assert profile == ("active", "Jane Doe", "es")
        assignments = await db.execute(
            select(func.count()).select_from(UserRoleAssignment).where(
                UserRoleAssignment.user_id == user.id
            )
        )
        assert assignments.scalar_one() == 1
