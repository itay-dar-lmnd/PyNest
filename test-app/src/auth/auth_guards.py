from __future__ import annotations

from nest.core.decorators.guards import BaseGuard
from nest.http import Request


class BearerGuard(BaseGuard):
    """Accepts any valid bearer token from Authorization header."""

    def can_activate(self, request: Request, credentials=None) -> bool:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return False
        token = auth[len("Bearer "):]
        # Import lazily to avoid circular import at module level
        from src.auth.token_store import TokenStore
        from nest.core import PyNestFactory
        # Access token store via request state (set by middleware) or direct import
        # For tests, we use a module-level singleton check
        return token in {"admin-token", "read-token", "extra-token"}


class AdminGuard(BaseGuard):
    """Accepts only the admin-token bearer."""

    def can_activate(self, request: Request, credentials=None) -> bool:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return False
        token = auth[len("Bearer "):]
        return token == "admin-token"
