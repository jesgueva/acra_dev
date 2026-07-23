from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role_name: str
    description: Optional[str] = None


class RoleList(BaseModel):
    results: List[RoleResponse]
