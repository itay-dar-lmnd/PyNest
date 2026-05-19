from __future__ import annotations

from nest.core import Module

from src.users.users_controller import UsersController
from src.users.users_service import UsersService


@Module(
    controllers=[UsersController],
    providers=[UsersService],
)
class UsersModule:
    pass
