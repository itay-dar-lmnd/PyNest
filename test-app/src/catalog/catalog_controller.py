from __future__ import annotations

from typing import List, Optional

from nest.core import Controller, Get, HttpCode, Post, Put
from nest.common.decorators import Body, Param, Query

from src.catalog.catalog_model import (
    CreateProductDto, ProductResponse, UpdateStockDto
)
from src.catalog.catalog_service import CatalogService


@Controller("/catalog", tag="catalog")
class CatalogController:
    def __init__(self, service: CatalogService) -> None:
        self.service = service

    @Get("")
    def list_products(
        self,
        tag: Optional[str] = Query("tag", default=None),
        min_stock: int = Query("min_stock", default=0),
    ) -> List[ProductResponse]:
        return self.service.find_all(tag=tag, min_stock=min_stock)

    @Post("")
    @HttpCode(201)
    def create_product(
        self,
        body: CreateProductDto = Body(),
    ) -> ProductResponse:
        return self.service.create(body)

    @Get("/{product_id}")
    def get_product(
        self,
        product_id: int = Param("product_id"),
    ) -> ProductResponse:
        return self.service.find_one(product_id)

    @Put("/{product_id}/stock")
    def update_stock(
        self,
        product_id: int = Param("product_id"),
        body: UpdateStockDto = Body(),
    ) -> ProductResponse:
        return self.service.update_stock(product_id, body)
