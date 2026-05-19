from __future__ import annotations

from nest.core import Module

from src.catalog.catalog_controller import CatalogController
from src.catalog.catalog_service import CatalogService


@Module(
    controllers=[CatalogController],
    providers=[CatalogService],
    exports=[CatalogService],   # exported so other modules can inject it
)
class CatalogModule:
    pass
