from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ContactBase(BaseModel):
    name: str = Field(..., max_length=200)
    type: str = Field(...)
    client_code: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    type: Optional[str] = None
    client_code: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class ContactResponse(ContactBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ContactListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[ContactResponse]
