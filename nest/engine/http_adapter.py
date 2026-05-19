from __future__ import annotations

from abc import ABCMeta, abstractmethod
from typing import Any, Callable, Generic, Optional, TypeVar

from nest.engine.route_spec import RouteSpec

TServer = TypeVar("TServer")
TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


class _ABCMetaMROFix(ABCMeta):
    """
    Minimal ABCMeta subclass that fixes a Python 3.9 bug where abstract
    methods are not resolved against the full MRO when a concrete mixin
    appears after the ABC in the bases tuple (e.g.
    ``type("X", (AbstractHttpAdapter, Mixin), {})``).

    In Python 3.10+ this is handled correctly by ABCMeta itself and this
    class becomes a no-op (the loop finds no remaining abstract methods).
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple,
        namespace: dict,
        **kwargs: Any,
    ) -> "_ABCMetaMROFix":
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        if not cls.__abstractmethods__:
            return cls
        remaining: set[str] = set()
        for method_name in cls.__abstractmethods__:
            for klass in cls.__mro__:
                if klass is cls:
                    continue
                impl = klass.__dict__.get(method_name)
                if impl is not None and not getattr(impl, "__isabstractmethod__", False):
                    break
            else:
                remaining.add(method_name)
        cls.__abstractmethods__ = frozenset(remaining)
        return cls


class AbstractHttpAdapter(
    Generic[TServer, TRequest, TResponse],
    metaclass=_ABCMetaMROFix,
):
    """
    Base class for PyNest HTTP engine adapters. NestJS-inspired.

    Wraps a web framework instance and exposes a neutral API for route
    registration, middleware, lifecycle hooks, exception handling, and
    request/response accessors.

    Key difference from NestJS AbstractHttpAdapter: add_route() accepts a
    full RouteSpec (including param bindings, guards, filters) because PyNest
    delegates validation and OpenAPI generation to the underlying framework
    rather than reimplementing them in core.
    """

    def __init__(self, instance: Optional[Any] = None) -> None:
        if instance is not None:
            self._instance: Any = instance
        else:
            # Walk the MRO to find the first concrete _create_instance
            # implementation.  This is necessary when the concrete provider
            # appears later in the MRO than AbstractHttpAdapter (e.g. when
            # using mixin-style composition via type()).
            for klass in type(self).__mro__:
                impl = klass.__dict__.get("_create_instance")
                if impl is not None and not getattr(impl, "__isabstractmethod__", False):
                    self._instance = impl(self)
                    break
            else:
                self._instance = None

    # ── concrete helpers ────────────────────────────────────────────────
    def get_http_server(self) -> Any:
        return self._instance

    def get_type(self) -> str:
        name = type(self).__name__
        if name.endswith("Adapter"):
            name = name[: -len("Adapter")]
        return name.lower()

    # ── server lifecycle ────────────────────────────────────────────────
    @abstractmethod
    def _create_instance(self) -> Any: ...

    @abstractmethod
    async def close(self) -> None: ...

    # ── route registration ──────────────────────────────────────────────
    @abstractmethod
    def add_route(self, spec: RouteSpec) -> None: ...

    @abstractmethod
    def add_websocket_route(
        self, path: str, endpoint: Callable[..., Any]
    ) -> None: ...

    # ── middleware / cors ───────────────────────────────────────────────
    @abstractmethod
    def use(self, middleware: Any, **options: Any) -> None: ...

    @abstractmethod
    def enable_cors(self, **options: Any) -> None: ...

    # ── lifecycle hooks ─────────────────────────────────────────────────
    @abstractmethod
    def register_startup_hook(self, fn: Callable[[], Any]) -> None: ...

    @abstractmethod
    def register_shutdown_hook(self, fn: Callable[[], Any]) -> None: ...

    # ── exception handling ──────────────────────────────────────────────
    @abstractmethod
    def register_exception_handler(
        self,
        exc_type: type,
        handler: Callable[..., Any],
    ) -> None: ...

    # ── NestJS-style request accessors ──────────────────────────────────
    @abstractmethod
    def get_request_method(self, req: Any) -> str: ...

    @abstractmethod
    def get_request_url(self, req: Any) -> str: ...

    @abstractmethod
    def get_request_hostname(self, req: Any) -> Optional[str]: ...

    @abstractmethod
    def get_request_headers(self, req: Any) -> dict: ...

    @abstractmethod
    def get_request_client_ip(self, req: Any) -> Optional[str]: ...

    # ── NestJS-style response writers ───────────────────────────────────
    @abstractmethod
    def reply(
        self, res: Any, body: Any, status_code: Optional[int] = None
    ) -> Any: ...

    @abstractmethod
    def set_header(self, res: Any, name: str, value: str) -> None: ...

    @abstractmethod
    def is_headers_sent(self, res: Any) -> bool: ...

    @abstractmethod
    def redirect(
        self, res: Any, url: str, status_code: int = 302
    ) -> Any: ...


__all__ = ["AbstractHttpAdapter"]
