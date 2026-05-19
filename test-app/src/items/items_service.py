from __future__ import annotations

from nest.core import Injectable

from src.items.items_model import CreateItemDto, ItemResponse


@Injectable
class ItemsService:
    def __init__(self) -> None:
        self._db: dict[int, ItemResponse] = {}
        self._next_id = 1

    def create(self, dto: CreateItemDto) -> ItemResponse:
        item = ItemResponse(
            id=self._next_id,
            name=dto.name,
            price=dto.price,
            in_stock=dto.in_stock,
        )
        self._db[self._next_id] = item
        self._next_id += 1
        return item

    def find_all(self, in_stock_only: bool = False) -> list[ItemResponse]:
        items = list(self._db.values())
        if in_stock_only:
            items = [i for i in items if i.in_stock]
        return items

    def find_one(self, item_id: int) -> ItemResponse | None:
        return self._db.get(item_id)
