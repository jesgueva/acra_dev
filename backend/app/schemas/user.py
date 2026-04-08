from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    username: str = Field(..., max_length=50)
    full_name: str = Field(..., max_length=150)
    password: str
    preferred_language: Literal["en", "es"] = "en"
    role_ids: List[int]


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=150)
    preferred_language: Optional[Literal["en", "es"]] = None
    status: Optional[Literal["active", "inactive"]] = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    roles: List[str] = []
    preferred_language: str
    status: str
    created_at: datetime


class PaginatedUsers(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[UserResponse]
