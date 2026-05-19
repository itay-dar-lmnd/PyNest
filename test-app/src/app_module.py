from __future__ import annotations

from nest.core import Module

from src.app_lifecycle import AppLifecycleService
from src.engine_check.engine_check_module import EngineCheckModule
from src.items.items_module import ItemsModule
from src.users.users_module import UsersModule


@Module(
    imports=[UsersModule, ItemsModule, EngineCheckModule],
    providers=[AppLifecycleService],
)
class AppModule:
    pass
