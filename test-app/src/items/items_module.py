from __future__ import annotations

from nest.core import Module

from src.items.items_controller import ItemsController
from src.items.items_service import ItemsService


@Module(
    controllers=[ItemsController],
    providers=[ItemsService],
)
class ItemsModule:
    pass
