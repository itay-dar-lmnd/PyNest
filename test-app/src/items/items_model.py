from __future__ import annotations

from pydantic import BaseModel


class CreateItemDto(BaseModel):
    name: str
    price: float
    in_stock: bool = True


class ItemResponse(BaseModel):
    id: int
    name: str
    price: float
    in_stock: bool
