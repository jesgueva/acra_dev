from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    username: str = Field(..., max_length=50)
    full_name: str = Field(..., max_length=150)
    password: str
    preferred_language: Literal["en", "es"] = "en"
    production_line: Optional[str] = Field(None, max_length=50)
    role_ids: List[int]


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, max_length=150)
    preferred_language: Optional[Literal["en", "es"]] = None
    status: Optional[Literal["active", "inactive"]] = None
    production_line: Optional[str] = Field(None, max_length=50)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    roles: List[str] = []
    preferred_language: str
    production_line: Optional[str] = None
    status: str
    created_at: datetime


class PaginatedUsers(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[UserResponse]


class SelfLanguageUpdate(BaseModel):
    preferred_language: Literal["en", "es"]


class ChangePasswordRequest(BaseModel):
    current_password: Optional[str] = None
    new_password: str


class RolesUpdate(BaseModel):
    role_ids: List[int]
