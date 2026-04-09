from app.core.security import hash_password
from app.models.user import User


def _make_user(password: str = "password123", status: str = "active") -> User:
    u = User()
    u.id = 1
    u.username = "testuser"
    u.full_name = "Test User"
    u.preferred_language = "en"
    u.status = status
    u.password_hash = hash_password(password)
    return u


def _override(session):
    async def _dep():
        yield session
    return _dep
