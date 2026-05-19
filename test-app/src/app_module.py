from __future__ import annotations

from nest.core import Module

from src.app_lifecycle import AppLifecycleService
from src.auth.auth_module import AuthModule
from src.catalog.catalog_module import CatalogModule
from src.engine_check.engine_check_module import EngineCheckModule
from src.items.items_module import ItemsModule
from src.pipeline.pipeline_module import PipelineModule
from src.users.users_module import UsersModule


@Module(
    imports=[
        UsersModule,
        ItemsModule,
        CatalogModule,      # exports CatalogService
        PipelineModule,
        AuthModule,         # imports CatalogModule (cross-module DI)
        EngineCheckModule,
    ],
    providers=[AppLifecycleService],
)
class AppModule:
    pass
