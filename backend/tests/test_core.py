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
