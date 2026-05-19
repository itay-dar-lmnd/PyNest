from nest.core import Controller, Get, HttpCode, Post
from nest.core.decorators.guards import UseGuards
from nest.core.decorators.filters import UseFilters
from nest.common.decorators import Body, Headers, Param, Query
from nest.common.exceptions import NotFoundException

from src.items.items_filter import HttpExceptionFilter
from src.items.items_guard import ApiKeyGuard
from src.items.items_model import CreateItemDto, ItemResponse
from src.items.items_service import ItemsService


@Controller("/items", tag="items")
@UseFilters(HttpExceptionFilter)
class ItemsController:
    def __init__(self, items_service: ItemsService) -> None:
        self.items_service = items_service

    @Get("/")
    def get_all(
        self,
        in_stock: bool = Query("in_stock", default=False),
    ) -> list[ItemResponse]:
        return self.items_service.find_all(in_stock_only=in_stock)

    @Post("/")
    @HttpCode(201)
    @UseGuards(ApiKeyGuard)
    def create(
        self,
        body: CreateItemDto = Body(),
        api_key: str = Headers("x-api-key", default=""),
    ) -> ItemResponse:
        return self.items_service.create(body)

    @Get("/{item_id}")
    def get_one(
        self,
        item_id: int = Param("item_id"),
    ) -> ItemResponse:
        item = self.items_service.find_one(item_id)
        if item is None:
            raise NotFoundException(f"Item {item_id} not found")
        return item
