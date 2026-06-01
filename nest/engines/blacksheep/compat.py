"""
Starlette-compatibility facades for the Blacksheep adapter.

PyNest's public ``nest.http.Request`` is Starlette's Request, and user code
(guards, custom param factories, controllers) is written against that surface:
``request.headers.get("authorization", "")``, ``request.query_params.get(...)``,
``request.path_params``, ``request.client.host``, ``await request.json()``.

Blacksheep's native request is shaped differently — bytes headers, ``.query``
returning ``dict[str, list[str]]``, ``.route_values`` instead of ``.path_params``.
``StarletteCompatRequest`` re-presents a Blacksheep request with the Starlette
subset that PyNest user code touches, so the same modules/controllers/guards run
unchanged under the Blacksheep engine. Anything not explicitly wrapped delegates
to the native request via ``__getattr__``.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

from starlette.websockets import WebSocketDisconnect

try:  # blacksheep raises this on the receiving side when the peer disconnects
    from blacksheep.server.websocket import WebSocketDisconnectError
except Exception:  # pragma: no cover - import guard
    WebSocketDisconnectError = ()  # type: ignore[assignment]


class _CompatHeaders:
    """Case-insensitive str view over Blacksheep's bytes ``Headers``."""

    def __init__(self, native: Any) -> None:
        self._native = native

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        raw = self._native.get_first(name.lower().encode())
        return raw.decode() if raw is not None else default

    def __getitem__(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise KeyError(name)
        return value

    def __contains__(self, name: str) -> bool:
        return self._native.contains(name.lower().encode())

    def items(self):
        for key, value in self._native.items():
            yield key.decode(), value.decode()

    def keys(self):
        return [k for k, _ in self.items()]


class _CompatQueryParams:
    """str view over Blacksheep's ``dict[str, list[str]]`` query."""

    def __init__(self, query: dict) -> None:
        self._query = query or {}

    def get(self, name: str, default: Optional[str] = None) -> Optional[str]:
        values = self._query.get(name)
        return values[0] if values else default

    def getlist(self, name: str) -> list:
        return list(self._query.get(name, []))

    def __getitem__(self, name: str) -> str:
        values = self._query.get(name)
        if not values:
            raise KeyError(name)
        return values[0]

    def __contains__(self, name: str) -> bool:
        return bool(self._query.get(name))

    def items(self):
        for key, values in self._query.items():
            yield key, (values[0] if len(values) == 1 else values)

    def keys(self):
        return list(self._query.keys())


class _CompatClient:
    __slots__ = ("host", "port")

    def __init__(self, host: Optional[str]) -> None:
        self.host = host
        self.port = None


class StarletteCompatRequest:
    """A Starlette-shaped view over a Blacksheep request (lazy, cached)."""

    def __init__(self, native: Any) -> None:
        self._native = native
        self._headers: Optional[_CompatHeaders] = None
        self._query: Optional[_CompatQueryParams] = None

    @property
    def headers(self) -> _CompatHeaders:
        if self._headers is None:
            self._headers = _CompatHeaders(self._native.headers)
        return self._headers

    @property
    def query_params(self) -> _CompatQueryParams:
        if self._query is None:
            self._query = _CompatQueryParams(self._native.query)
        return self._query

    @property
    def path_params(self) -> dict:
        return dict(self._native.route_values or {})

    @property
    def client(self) -> _CompatClient:
        return _CompatClient(self._native.client_ip)

    @property
    def method(self) -> str:
        return self._native.method

    async def json(self) -> Any:
        return await self._native.json()

    async def body(self) -> bytes:
        return await self._native.read()

    def __getattr__(self, name: str) -> Any:
        # Delegate anything we didn't override (scope, cookies, url, user, ...).
        return getattr(self._native, name)


class StarletteCompatWebSocket:
    """
    Presents a Blacksheep WebSocket with the Starlette-ish surface the PyNest
    WebSocket gateway uses (``accept`` / ``receive_json`` / ``send_json`` /
    ``close``), translating Blacksheep's ``WebSocketDisconnectError`` into
    Starlette's ``WebSocketDisconnect`` so the gateway's receive loop terminates
    and runs its disconnect cleanup. A single instance is reused for the whole
    connection so identity-based subscription bookkeeping stays stable.
    """

    def __init__(self, native: Any) -> None:
        self._native = native
        # Starlette WebSockets expose a ``.state`` namespace that PyNest's
        # WebSocketServer uses to stash a per-connection client id. Blacksheep's
        # WebSocket has none — provide one (persists for the connection since a
        # single shim instance is reused).
        self.state = SimpleNamespace()

    async def accept(self, *args: Any, **kwargs: Any) -> None:
        await self._native.accept()

    async def receive_json(self) -> Any:
        try:
            return await self._native.receive_json()
        except WebSocketDisconnectError as exc:  # type: ignore[misc]
            code = getattr(exc, "code", 1000)
            raise WebSocketDisconnect(code=code) from exc

    async def send_json(self, data: Any) -> None:
        await self._native.send_json(data)

    async def close(self, code: int = 1000, reason: Optional[str] = None) -> None:
        await self._native.close(code=code, reason=reason)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._native, name)
