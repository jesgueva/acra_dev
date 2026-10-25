"""
Create — or reset the password of — a company_admin on a deployed database, without demo data.

A freshly migrated database has roles but no users. The only other way to get one is
`seed_fake_data.py`, which also writes demo deliveries and work orders plus five logins whose
passwords are printed in the README: right for development and e2e, wrong for anything reachable
from the internet. This script is the production half of the seed — the roles' privileges and one
administrator, nothing else.

Usage, from a shell inside the running backend container (`railway ssh --service backend`):

    python scripts/bootstrap_admin.py --username jdoe --full-name "Jane Doe"
    # prompts for the password twice; or non-interactively:
    printf '%s' "$PASSWORD" | python scripts/bootstrap_admin.py --username jdoe --password-stdin

Re-running with an existing username resets that user's password, re-activates them and makes sure
they hold company_admin — the recovery path for a locked-out administrator. Their name, language and
production line are kept unless passed explicitly.

Privileges come from `seed_fake_data.ROLE_DEFINITIONS`, never a list of this script's own: a
previous `create_admin.py` kept its own list, drifted to names no router checks, and was deleted for
it (see tests/test_privilege_parity.py). Applying ROLE_DEFINITIONS also grants `receiving.view` —
the frontend-only privilege no migration grants, which gates the Receiving and Contacts navigation —
so a deployed database's roles match what the e2e suite runs against. It only ever adds grants.
"""

import argparse
import asyncio
import getpass
import os
import sys

# Allow running from backend/ root or from scripts/ — same as seed_fake_data.py.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.audit import write_audit
from app.models.user import Role, User
from scripts.seed_fake_data import (
    DATABASE_URL,
    ROLE_DEFINITIONS,
    ensure_role_privileges,
    ensure_user,
    ensure_user_role,
)

ADMIN_ROLE = "company_admin"
MIN_PASSWORD_LENGTH = 12
USERNAME_MAX_LENGTH = 50  # users.username is String(50); UserCreate enforces the same.


async def bootstrap_admin(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    full_name: str | None = None,
    preferred_language: str | None = None,
) -> bool:
    """Grant ROLE_DEFINITIONS' privileges and make `username` an active company_admin.

    Returns True when the user was created, False when an existing one was reset. The caller
    commits, as with every other writer here.
    """
    roles: dict[str, Role] = {}
    for role_name, definition in ROLE_DEFINITIONS.items():
        role = (
            await db.execute(select(Role).where(Role.role_name == role_name))
        ).scalar_one_or_none()
        if role is None:
            # Roles are created by migration 001. Their absence means the schema is not at head —
            # creating them here would paper over that.
            raise RuntimeError(f"role {role_name!r} is missing — run `alembic upgrade head` first")
        await ensure_role_privileges(db, role, set(definition["privileges"]))
        roles[role_name] = role

    existing = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    user, created = await ensure_user(
        db,
        username=username,
        password=password,
        full_name=full_name or (existing.full_name if existing else "Administrator"),
        preferred_language=preferred_language
        or (existing.preferred_language if existing else "en"),
        production_line=existing.production_line if existing else None,
    )
    await ensure_user_role(db, user.id, roles[ADMIN_ROLE].id)
    await write_audit(
        db,
        None,  # no authenticated actor: this runs from a shell on the server
        "create_user" if created else "update_user",
        "user",
        user.id,
        {"username": username, "role": ADMIN_ROLE, "via": "scripts/bootstrap_admin.py"},
    )
    return created


def read_password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            raise SystemExit("Passwords do not match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


def username_arg(raw: str) -> str:
    value = raw.strip()
    if not value or len(value) > USERNAME_MAX_LENGTH:
        raise argparse.ArgumentTypeError(f"must be 1-{USERNAME_MAX_LENGTH} characters")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or reset a company_admin, without demo data.",
    )
    parser.add_argument("--username", required=True, type=username_arg)
    parser.add_argument("--full-name", help="defaults to 'Administrator' for a new user")
    parser.add_argument("--language", choices=["en", "es"], help="defaults to 'en' for a new user")
    parser.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from the first line of stdin instead of prompting",
    )
    return parser


async def _run(args: argparse.Namespace, password: str) -> bool:
    engine = create_async_engine(DATABASE_URL, echo=False)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            created = await bootstrap_admin(
                db,
                username=args.username,
                password=password,
                full_name=args.full_name,
                preferred_language=args.language,
            )
            await db.commit()
    finally:
        await engine.dispose()
    return created


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    password = read_password(args.password_stdin)
    try:
        created = asyncio.run(_run(args, password))
    except RuntimeError as exc:
        print(f"Bootstrap aborted: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    action = "Created" if created else "Reset the password of"
    print(f"{action} {ADMIN_ROLE} {args.username!r}. Sign in and create everyone else under Users.")


if __name__ == "__main__":
    main()
