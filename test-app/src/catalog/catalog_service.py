from __future__ import annotations

from typing import List, Optional
from nest.core import Injectable
from nest.common.exceptions import NotFoundException, ConflictException

from src.catalog.catalog_model import (
    CreateProductDto, ProductResponse, UpdateStockDto
)


@Injectable
class CatalogService:
    def __init__(self) -> None:
        self._products: dict[int, ProductResponse] = {}
        self._next_id = 1

    def create(self, dto: CreateProductDto) -> ProductResponse:
        skus = [v.sku for v in dto.variants]
        if len(skus) != len(set(skus)):
            raise ConflictException("Duplicate SKU in variants")
        product = ProductResponse.from_dto(self._next_id, dto)
        self._products[self._next_id] = product
        self._next_id += 1
        return product

    def find_all(
        self,
        tag: Optional[str] = None,
        min_stock: int = 0,
    ) -> List[ProductResponse]:
        products = list(self._products.values())
        if tag:
            products = [p for p in products if any(t.name == tag for t in p.tags)]
        if min_stock > 0:
            products = [p for p in products if p.total_stock >= min_stock]
        return products

    def find_one(self, product_id: int) -> ProductResponse:
        p = self._products.get(product_id)
        if p is None:
            raise NotFoundException(f"Product {product_id} not found")
        return p

    def update_stock(self, product_id: int, dto: UpdateStockDto) -> ProductResponse:
        product = self.find_one(product_id)
        variant = next((v for v in product.variants if v.sku == dto.sku), None)
        if variant is None:
            raise NotFoundException(f"SKU {dto.sku} not found in product {product_id}")
        new_stock = variant.stock + dto.delta
        if new_stock < 0:
            raise ConflictException(f"Stock cannot go below 0 (current: {variant.stock})")
        updated_variants = [
            v.model_copy(update={"stock": new_stock}) if v.sku == dto.sku else v
            for v in product.variants
        ]
        updated = product.model_copy(
            update={
                "variants": updated_variants,
                "total_stock": sum(v.stock for v in updated_variants),
            }
        )
        self._products[product_id] = updated
        return updated
