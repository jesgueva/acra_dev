"""`scripts/bootstrap_admin.py` without a database — the parts that decide, not those that write.

The writer itself runs against a real, migrated database in
`tests/integration/test_bootstrap_admin.py`.
"""
import io
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts import bootstrap_admin, seed_fake_data


def test_privileges_come_from_the_seed_not_a_list_of_its_own():
    """The predecessor `create_admin.py` kept its own privilege list, drifted, and was deleted.

    Sharing the seed's object (not a copy) is what keeps tests/test_privilege_parity.py — which
    checks ROLE_DEFINITIONS against the routers and frontend — covering this script too.
    """
    assert bootstrap_admin.ROLE_DEFINITIONS is seed_fake_data.ROLE_DEFINITIONS
    assert bootstrap_admin.ADMIN_ROLE in seed_fake_data.ROLE_DEFINITIONS


def test_password_from_stdin_drops_only_the_line_ending(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("  correct horse battery  \r\n"))
    assert bootstrap_admin.read_password(from_stdin=True) == "  correct horse battery  "


@pytest.mark.parametrize("password", ["", "short", "x" * (bootstrap_admin.MIN_PASSWORD_LENGTH - 1)])
def test_password_shorter_than_the_minimum_is_refused(monkeypatch, password):
    monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
    with pytest.raises(SystemExit, match="at least"):
        bootstrap_admin.read_password(from_stdin=True)


def test_prompted_password_must_be_typed_twice_identically(monkeypatch):
    answers = iter(["first-password-123", "second-password-456"])
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(answers))
    with pytest.raises(SystemExit, match="do not match"):
        bootstrap_admin.read_password(from_stdin=False)


def test_prompted_password_is_returned_when_confirmed(monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt: "a-long-enough-password")
    assert bootstrap_admin.read_password(from_stdin=False) == "a-long-enough-password"


@pytest.mark.parametrize("username", ["", "   ", "u" * (bootstrap_admin.USERNAME_MAX_LENGTH + 1)])
def test_parser_rejects_usernames_the_users_table_cannot_hold(username):
    with pytest.raises(SystemExit):
        bootstrap_admin.build_parser().parse_args(["--username", username])


def test_parser_defaults_leave_the_profile_untouched():
    """None, not "Administrator"/"en": a reset must keep an existing admin's name and language."""
    args = bootstrap_admin.build_parser().parse_args(["--username", " jdoe "])
    assert (args.username, args.full_name, args.language, args.password_stdin) == (
        "jdoe",
        None,
        None,
        False,
    )


async def test_missing_role_aborts_instead_of_creating_it():
    """No roles means migrations have not run — the script must say so, not invent the roles."""
    db = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result)

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        await bootstrap_admin.bootstrap_admin(db, username="jdoe", password="irrelevant-here")
    db.add.assert_not_called()


def test_main_turns_a_failed_bootstrap_into_exit_code_1(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("a-long-enough-password\n"))

    async def _fail(args, password):
        raise RuntimeError("role 'company_admin' is missing — run `alembic upgrade head` first")

    monkeypatch.setattr(bootstrap_admin, "_run", _fail)
    with pytest.raises(SystemExit) as excinfo:
        bootstrap_admin.main(["--username", "jdoe", "--password-stdin"])
    assert excinfo.value.code == 1
    assert "alembic upgrade head" in capsys.readouterr().err
