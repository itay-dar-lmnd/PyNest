from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class Dimension(BaseModel):
    width: float
    height: float
    depth: float


class Tag(BaseModel):
    name: str
    color: str = "gray"


class Variant(BaseModel):
    sku: str
    price: float
    stock: int = 0
    attributes: dict = Field(default_factory=dict)


class CreateProductDto(BaseModel):
    name: str
    description: Optional[str] = None
    variants: List[Variant]
    dimensions: Optional[Dimension] = None
    tags: List[Tag] = Field(default_factory=list)


class ProductResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    variants: List[Variant]
    dimensions: Optional[Dimension]
    tags: List[Tag]
    total_stock: int

    @classmethod
    def from_dto(cls, product_id: int, dto: CreateProductDto) -> ProductResponse:
        return cls(
            id=product_id,
            name=dto.name,
            description=dto.description,
            variants=dto.variants,
            dimensions=dto.dimensions,
            tags=dto.tags,
            total_stock=sum(v.stock for v in dto.variants),
        )


class UpdateStockDto(BaseModel):
    sku: str
    delta: int  # positive = add, negative = subtract
