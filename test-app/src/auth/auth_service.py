from __future__ import annotations

from nest.core import Injectable

from src.auth.token_store import TokenStore
from src.catalog.catalog_service import CatalogService


@Injectable
class AuthService:
    """
    Demonstrates cross-module DI: AuthService injects both TokenStore (same module)
    and CatalogService (exported by CatalogModule).
    """

    def __init__(
        self,
        token_store: TokenStore,
        catalog_service: CatalogService,
    ) -> None:
        self.token_store = token_store
        self.catalog_service = catalog_service

    def validate_and_get_products(self, token: str) -> dict:
        valid = self.token_store.is_valid(token)
        products = self.catalog_service.find_all() if valid else []
        return {
            "token_valid": valid,
            "is_admin": self.token_store.is_admin(token),
            "accessible_products": len(products),
        }
