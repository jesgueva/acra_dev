from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, String, TIMESTAMP
from sqlalchemy.sql import func

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(150), nullable=False)
    preferred_language = Column(String(10), nullable=False, server_default="en")
    status = Column(String(20), nullable=False, server_default="active")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_users_status"),
    )


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    role_name = Column(String(100), nullable=False, unique=True)
    description = Column(String, nullable=True)


class UserRoleAssignment(Base):
    __tablename__ = "user_role_assignments"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    assigned_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
