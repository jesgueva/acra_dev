from typing import List

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenUser(BaseModel):
    user_id: int
    full_name: str
    roles: List[str]
    preferred_language: str
    effective_privileges: List[str] = []
    production_line: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: TokenUser
