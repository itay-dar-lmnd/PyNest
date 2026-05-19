from __future__ import annotations

from nest.core import Module

from src.auth.auth_controller import AuthController
from src.auth.auth_service import AuthService
from src.auth.token_store import TokenStore
from src.catalog.catalog_module import CatalogModule


@Module(
    imports=[CatalogModule],        # uses CatalogService via export
    controllers=[AuthController],
    providers=[TokenStore, AuthService],
    exports=[TokenStore],           # TokenStore exported for potential future use
)
class AuthModule:
    pass
