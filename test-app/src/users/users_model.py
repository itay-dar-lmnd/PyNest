from __future__ import annotations

from pydantic import BaseModel


class CreateUserDto(BaseModel):
    name: str
    email: str


class UserResponse(BaseModel):
    id: int
    name: str
    email: str
