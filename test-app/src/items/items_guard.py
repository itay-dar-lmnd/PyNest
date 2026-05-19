from __future__ import annotations

from nest.core.decorators.guards import BaseGuard

# Uses nest.http.Request (the new facade) instead of fastapi.Request directly
from nest.http import Request


class ApiKeyGuard(BaseGuard):
    """Checks for X-API-Key: secret header. Exercises guard + nest.http.Request."""

    def can_activate(self, request: Request, credentials=None) -> bool:
        return request.headers.get("x-api-key") == "secret"
