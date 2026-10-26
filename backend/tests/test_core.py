"""
Unit tests for T04 — Core Backend Infrastructure.
All tests run without a live database connection.
"""
import inspect
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from jose import JWTError


# ---------------------------------------------------------------------------
# 1. JWT round-trip
# ---------------------------------------------------------------------------
def test_create_and_verify_token():
    from app.core.security import create_access_token, verify_token

    token = create_access_token(user_id=42)
    assert isinstance(token, str)
    assert verify_token(token) == 42


# ---------------------------------------------------------------------------
# 2. Expired / invalid token raises JWTError
# ---------------------------------------------------------------------------
def test_verify_token_rejects_invalid():
    from app.core.security import create_access_token, verify_token

    expired = create_access_token(user_id=1, expires_delta=timedelta(seconds=-1))
    with pytest.raises(JWTError):
        verify_token(expired)

    with pytest.raises(JWTError):
        verify_token("not.a.valid.token")


# ---------------------------------------------------------------------------
# 3. Password hash round-trip
# ---------------------------------------------------------------------------
def test_hash_and_verify_password():
    from app.core.security import hash_password, verify_password

    hashed = hash_password("supersecret")
    assert hashed != "supersecret"
    assert verify_password("supersecret", hashed) is True
    assert verify_password("wrong", hashed) is False


# ---------------------------------------------------------------------------
# 4. require_privilege factory returns an async callable
# ---------------------------------------------------------------------------
def test_require_privilege_returns_callable():
    from app.core.rbac import require_privilege

    dep = require_privilege("inventory.view")
    assert callable(dep)
    assert inspect.iscoroutinefunction(dep)


# ---------------------------------------------------------------------------
# 5. write_audit adds an AuditLog entry to the session
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_write_audit_adds_to_session():
    from app.core.audit import write_audit

    mock_db = AsyncMock()
    mock_db.add = MagicMock()

    await write_audit(
        db=mock_db,
        user_id=7,
        action="login",
        entity_type="user",
        entity_id=7,
        details={"ip": "127.0.0.1"},
    )

    mock_db.add.assert_called_once()
    added = mock_db.add.call_args[0][0]
    from app.models.audit import AuditLog

    assert isinstance(added, AuditLog)
    assert added.user_id == 7
    assert added.action == "login"
    assert added.entity_type == "user"


# ---------------------------------------------------------------------------
# 6. CORS origin parsing (ACR-21)
# ---------------------------------------------------------------------------
# The origin list used to be hard-coded to localhost:3000, which silently CORS-blocked every
# browser XHR whenever the frontend ran anywhere else — a second worktree, or an e2e run on a
# free port. These cover the parsing that replaced it.
def test_cors_origin_list_splits_and_strips():
    from app.core.config import Settings

    settings = Settings(cors_origins="http://localhost:3000, http://localhost:3200")
    assert settings.cors_origin_list == [
        "http://localhost:3000",
        "http://localhost:3200",
    ]


def test_cors_origin_list_defaults_to_the_documented_dev_port():
    from app.core.config import Settings

    # Assert the *declared* default rather than `Settings().cors_origins`: instantiating reads the
    # developer's local .env, so the latter would pass or fail depending on whose machine ran it.
    default = Settings.model_fields["cors_origins"].default
    assert default == "http://localhost:3000"
    assert Settings(cors_origins=default).cors_origin_list == ["http://localhost:3000"]


def test_cors_origin_list_ignores_blank_entries():
    from app.core.config import Settings

    settings = Settings(cors_origins="http://a.test,, ,http://b.test,")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]


# ---------------------------------------------------------------------------
# 7. Production refuses an insecure SECRET_KEY (Railway deploy)
# ---------------------------------------------------------------------------
# The Railway IaC ships without secret values, so "deployed before SECRET_KEY was set" is a real
# first-deploy state. Without the guard the API would boot and sign JWTs with the committed default.
STRONG_SECRET = "x" * 48


@pytest.mark.parametrize(
    "secret_key",
    ["dev-secret-key-change-in-production", "", "short-but-not-empty", "y" * 31],
    ids=["committed-default", "empty", "short", "one-under-minimum"],
)
def test_production_refuses_an_insecure_secret_key(secret_key):
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="production", secret_key=secret_key)


@pytest.mark.parametrize("app_env", ["Production", " PRODUCTION "])
def test_production_is_recognised_whatever_its_case(app_env):
    """A hand-typed `Production` in a dashboard must not silently switch the guard off."""
    from pydantic import ValidationError

    from app.core.config import DEV_SECRET_KEY, Settings

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env=app_env, secret_key=DEV_SECRET_KEY)


def test_production_accepts_a_strong_secret_key():
    from app.core.config import MIN_PRODUCTION_SECRET_KEY_LENGTH, Settings

    assert Settings(app_env="production", secret_key=STRONG_SECRET).secret_key == STRONG_SECRET
    exact = "z" * MIN_PRODUCTION_SECRET_KEY_LENGTH
    assert Settings(app_env="production", secret_key=exact).secret_key == exact


def test_development_keeps_the_dev_default():
    """Local dev, CI and compose never set APP_ENV — the guard must not touch them."""
    from app.core.config import DEV_SECRET_KEY, Settings

    assert Settings.model_fields["app_env"].default == "development"
    assert Settings(app_env="development", secret_key=DEV_SECRET_KEY).secret_key == DEV_SECRET_KEY
