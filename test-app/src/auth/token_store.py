from __future__ import annotations

from nest.core import Injectable


@Injectable
class TokenStore:
    """In-memory token registry — shared provider exported by AuthModule."""

    def __init__(self) -> None:
        self._tokens: set[str] = {"admin-token", "read-token"}

    def is_valid(self, token: str) -> bool:
        return token in self._tokens

    def is_admin(self, token: str) -> bool:
        return token == "admin-token"

    def add_token(self, token: str) -> None:
        self._tokens.add(token)

    def revoke_token(self, token: str) -> None:
        self._tokens.discard(token)
