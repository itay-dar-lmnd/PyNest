"""
Litestar implementation of AbstractHttpAdapter.

Translates PyNest's neutral RouteSpec into Litestar's route handlers and
plumbing. Mirrors the FastAPI adapter conceptually, but emits Litestar's
``@get(...)`` / ``@post(...)`` / ``Parameter(...)`` / ``Provide(...)``
primitives instead of FastAPI's add_api_route + Depends.

Notable Litestar-specific behaviour:
  - Path-param types are encoded in the URL template (e.g. ``/{id:int}``),
    not on the handler signature. The adapter rewrites paths accordingly.
  - Default POST status is 201; the adapter explicitly forwards spec.status_code.
  - CORS is configured via ``CORSConfig`` at Litestar() construction time;
    the adapter rebuilds the app the first time ``enable_cors`` is called
    if it must happen post-construction.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Optional

from litestar import Litestar, delete, get, patch, post, put, websocket
from litestar.config.cors import CORSConfig
from litestar.connection import ASGIConnection
from litestar.exceptions import HTTPException as LitestarHTTPException
from litestar.exceptions import PermissionDeniedException
from litestar.handlers.base import BaseRouteHandler
from litestar.response import Redirect, Response

from nest.engine._shared import NO_FILTER_MATCH, run_filters
from nest.engine._shared import extract_credentials as _extract_credentials
from nest.engine.http_adapter import AbstractHttpAdapter
from nest.engine.route_spec import RouteSpec
from nest.engine.types import HttpMethod
from nest.engines.litestar.params import (
    bind_params,
    has_param_specs,
    rewrite_path_with_types,
)


# Map our HttpMethod values to Litestar's decorator functions.
_METHOD_DECORATORS = {
    HttpMethod.GET: get,
    HttpMethod.POST: post,
    HttpMethod.PUT: put,
    HttpMethod.PATCH: patch,
    HttpMethod.DELETE: delete,
}


class LitestarAdapter(AbstractHttpAdapter[Litestar, ASGIConnection, Response]):
    """
    PyNest's Litestar engine adapter. Wraps a Litestar instance.

    Construct with no arguments, with ``**litestar_kwargs`` to forward to
    ``Litestar(...)``, or with ``instance=`` to wrap an existing Litestar app.
    """

    def __init__(
        self,
        instance: Optional[Litestar] = None,
        **litestar_kwargs: Any,
    ) -> None:
        self._litestar_kwargs = litestar_kwargs
        # Litestar collects route_handlers/on_startup/on_shutdown at
        # construction; we use mutable lists so subsequent registrations work.
        self._exception_handlers: dict[type, Callable] = {}
        super().__init__(instance)

    # ── server lifecycle ────────────────────────────────────────────────

    def _create_instance(self) -> Litestar:
        # Pre-seed exception_handlers so post-construction registration works.
        kwargs = dict(self._litestar_kwargs)
        kwargs.setdefault("exception_handlers", self._exception_handlers)
        kwargs.setdefault("route_handlers", [])
        # Default openapi config — Litestar mounts the schema under
        # ``path``. We pick ``/docs`` so the UI lives at /docs (FastAPI parity)
        # and the JSON schema at /docs/openapi.json.
        if "openapi_config" not in kwargs:
            from litestar.openapi.config import OpenAPIConfig
            kwargs["openapi_config"] = OpenAPIConfig(
                title=kwargs.pop("title", "PyNest App"),
                version=kwargs.pop("version", "0.7.0"),
                description=kwargs.pop("description", "Built with PyNest"),
                path="/docs",
            )
        return Litestar(**kwargs)

    async def close(self) -> None:
        return None

    # ── route registration (central entry point) ────────────────────────

    def add_route(self, spec: RouteSpec) -> None:
        endpoint = spec.endpoint
        dependencies: dict[str, Any] = {}
        if has_param_specs(endpoint):
            endpoint = bind_params(endpoint)
            dependencies.update(getattr(endpoint, "__litestar_dependencies__", {}))

        if spec.filters:
            endpoint = _wrap_with_filters(endpoint, spec.filters)

        # Translate the path with Litestar-specific type tokens.
        litestar_path = rewrite_path_with_types(spec.path, spec.params)

        # Translate guards.
        guards = [_guard_to_litestar(g) for g in spec.guards] if spec.guards else None

        decorator_kwargs: dict[str, Any] = {}
        if spec.status_code is not None:
            decorator_kwargs["status_code"] = spec.status_code
        elif spec.method == HttpMethod.DELETE:
            # Litestar defaults DELETE to 204 (no body), but PyNest endpoints
            # commonly return a confirmation body. Default to 200 to match
            # FastAPI's behaviour and keep handlers cross-engine.
            decorator_kwargs["status_code"] = 200
        elif spec.method == HttpMethod.POST:
            # Litestar defaults POST to 201; FastAPI defaults to 200. Match
            # FastAPI for cross-engine consistency unless the handler explicitly
            # opts into 201 via @HttpCode(201).
            decorator_kwargs["status_code"] = 200
        if spec.tags:
            decorator_kwargs["tags"] = list(spec.tags)
        if spec.name:
            decorator_kwargs["name"] = spec.name
        if spec.summary:
            decorator_kwargs["summary"] = spec.summary
        if spec.description:
            decorator_kwargs["description"] = spec.description
        if guards:
            decorator_kwargs["guards"] = guards
        if dependencies:
            decorator_kwargs["dependencies"] = dependencies
        # Allow adapter-specific extras to win (e.g. response_class, media_type, etc.)
        for k, v in spec.extra.items():
            decorator_kwargs.setdefault(k, v)

        decorator = _METHOD_DECORATORS.get(spec.method)
        if decorator is None:
            # Fallback for HEAD/OPTIONS: use route() with explicit method
            from litestar import route
            handler = route(http_method=spec.method.value, path=litestar_path, **decorator_kwargs)(endpoint)
        else:
            handler = decorator(litestar_path, **decorator_kwargs)(endpoint)

        self._instance.register(handler)

    def add_websocket_route(self, path: str, endpoint: Callable[..., Any]) -> None:
        handler = websocket(path)(endpoint)
        self._instance.register(handler)

    # ── middleware / CORS ───────────────────────────────────────────────

    def use(self, middleware: Any, **options: Any) -> None:
        # Litestar's middleware list is mutable.
        if options:
            # Wrap factory-style middleware so options flow through.
            self._instance.middleware.append(
                lambda app, _opts=options, _cls=middleware: _cls(app, **_opts)
            )
        else:
            self._instance.middleware.append(middleware)

    def enable_cors(self, **options: Any) -> None:
        # Litestar prefers CORSConfig set at construction. Post-construction we
        # attach a CORS middleware via the standard ASGI hook.
        cors_config = CORSConfig(**options)
        # The simplest path: rebuild the app with cors_config. But that wipes
        # already-registered routes. Instead, attach CORS as ASGI middleware.
        from litestar.middleware.cors import CORSMiddleware
        self._instance.middleware.append(
            lambda app: CORSMiddleware(app=app, config=cors_config)
        )

    # ── lifecycle hooks ─────────────────────────────────────────────────

    def register_startup_hook(self, fn: Callable[[], Any]) -> None:
        self._instance.on_startup.append(fn)

    def register_shutdown_hook(self, fn: Callable[[], Any]) -> None:
        self._instance.on_shutdown.append(fn)

    # ── exception handling ──────────────────────────────────────────────

    def register_exception_handler(
        self,
        exc_type: type,
        handler: Callable[..., Any],
    ) -> None:
        # Litestar calls exception handlers synchronously. Sync handlers are
        # required (FastAPI accepts both sync and async). Cross-engine code
        # should use sync `def`.
        # We also wrap the handler so users can return a Starlette/FastAPI
        # JSONResponse and have it converted to a Litestar Response — making
        # the same exception filter portable across engines.
        wrapped = _wrap_exception_handler_for_litestar(handler)
        self._instance.exception_handlers[exc_type] = wrapped
        self._exception_handlers[exc_type] = wrapped

    # ── NestJS-style request accessors ──────────────────────────────────

    def get_request_method(self, req: Any) -> str:
        return req.method

    def get_request_url(self, req: Any) -> str:
        return str(req.url)

    def get_request_hostname(self, req: Any) -> Optional[str]:
        return req.url.hostname

    def get_request_headers(self, req: Any) -> dict:
        return dict(req.headers)

    def get_request_client_ip(self, req: Any) -> Optional[str]:
        return req.client.host if getattr(req, "client", None) else None

    # ── NestJS-style response writers ───────────────────────────────────

    def reply(
        self,
        res: Any,
        body: Any,
        status_code: Optional[int] = None,
    ) -> Any:
        return Response(content=body, status_code=status_code or 200)

    def set_header(self, res: Any, name: str, value: str) -> None:
        res.headers[name] = value

    def is_headers_sent(self, res: Any) -> bool:
        return False

    def redirect(self, res: Any, url: str, status_code: int = 302) -> Any:
        return Redirect(path=url, status_code=status_code)


# ── translation helpers ──────────────────────────────────────────────────────


def _convert_to_litestar_response(result: Any) -> Any:
    """Convert a Starlette/FastAPI Response to a Litestar Response (no-op if already native)."""
    import json as _json
    if result is None:
        return None
    # Already a Litestar Response — pass through.
    if hasattr(result, "to_asgi_response"):
        return result
    # Starlette/FastAPI Response has .body and .status_code
    if hasattr(result, "body") and hasattr(result, "status_code"):
        try:
            body = _json.loads(result.body)
        except Exception:
            body = result.body
        return Response(
            content=body,
            status_code=result.status_code,
            media_type=getattr(result, "media_type", "application/json"),
        )
    # Plain dict/list/string — Litestar will serialize automatically.
    return result


def _wrap_exception_handler_for_litestar(handler: Callable) -> Callable:
    """
    Wrap a user-supplied exception handler so its return value works with Litestar.

    Users (and PyNest's own filter machinery) may return a Starlette/FastAPI
    ``JSONResponse``. Litestar expects a Litestar ``Response``. We translate
    automatically so the same handler is portable across engines.
    """
    import json as _json

    def wrapped(request, exc):
        result = handler(request, exc)
        # If it's already a Litestar Response (has .to_asgi_response), return as-is.
        if hasattr(result, "to_asgi_response"):
            return result
        # If it's a Starlette/FastAPI Response (has .status_code and .body),
        # convert to a Litestar Response.
        if hasattr(result, "body") and hasattr(result, "status_code"):
            try:
                body = _json.loads(result.body)
            except Exception:
                body = result.body
            return Response(
                content=body,
                status_code=result.status_code,
                media_type=getattr(result, "media_type", "application/json"),
            )
        # Otherwise treat as raw content.
        return Response(content=result)

    return wrapped


def _guard_to_litestar(guard: Any) -> Callable:
    """
    Translate a PyNest BaseGuard (instance or class) into a Litestar guard.

    Litestar guards have signature ``(connection, route_handler) -> None``
    and raise on denial. We adapt PyNest's ``can_activate(request, credentials)``
    to that contract.
    """
    if inspect.isclass(guard):
        guard_instance = guard()
    else:
        guard_instance = guard

    async def litestar_guard(connection: ASGIConnection, _: BaseRouteHandler) -> None:
        # PyNest guards expect a request-like object. ASGIConnection has the
        # same .headers / .url / .client interface as a Request.
        credentials = None
        if guard_instance.security_scheme is not None:
            # Best-effort: extract from headers based on the security scheme name.
            credentials = _extract_credentials(connection, guard_instance.security_scheme)
        result = guard_instance.can_activate(connection, credentials)
        if inspect.isawaitable(result):
            result = await result
        if not result:
            raise PermissionDeniedException(detail="Access denied: insufficient permissions")

    litestar_guard.__name__ = f"guard_{type(guard_instance).__name__}"
    return litestar_guard


def _wrap_with_filters(endpoint: Callable, filters: tuple) -> Callable:
    """
    Wrap an endpoint so exceptions route through PyNest ExceptionFilter instances.

    Same algorithm as the FastAPI adapter — the filter contract is engine-neutral.
    """
    import typing as _typing
    from litestar.connection import Request as LitestarRequest

    original_sig = inspect.signature(endpoint)
    existing_params = list(original_sig.parameters.values())
    has_request = any(p.name == "request" for p in existing_params)

    if not has_request:
        request_param = inspect.Parameter(
            "request",
            inspect.Parameter.KEYWORD_ONLY,
            annotation=LitestarRequest,
        )
        wrapper_sig = original_sig.replace(
            parameters=existing_params + [request_param]
        )
    else:
        wrapper_sig = original_sig

    orig_param_names = {p.name for p in existing_params}

    async def filter_wrapper(*args, **kwargs):
        request = kwargs.get("request")
        call_kwargs = {k: v for k, v in kwargs.items() if k in orig_param_names}
        try:
            result = endpoint(*args, **call_kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as exc:
            # Convert Starlette/FastAPI JSONResponse → Litestar Response so
            # per-route filters work the same regardless of engine.
            result = await run_filters(
                exc, request, filters, convert=_convert_to_litestar_response
            )
            if result is NO_FILTER_MATCH:
                raise
            return result

    filter_wrapper.__name__ = getattr(endpoint, "__name__", "filter_wrapper")
    filter_wrapper.__signature__ = wrapper_sig
    # Build __annotations__ from the wrapper signature so Litestar's signature
    # validator finds proper types for all parameters (including the synthetic
    # `request: Request` we just added when no request parameter existed).
    new_annotations: dict[str, Any] = {}
    for p in wrapper_sig.parameters.values():
        if p.annotation is not inspect.Parameter.empty:
            new_annotations[p.name] = p.annotation
    if wrapper_sig.return_annotation is not inspect.Signature.empty:
        new_annotations["return"] = wrapper_sig.return_annotation
    filter_wrapper.__annotations__ = new_annotations
    # Carry forward litestar dependencies if any
    filter_wrapper.__litestar_dependencies__ = getattr(  # type: ignore[attr-defined]
        endpoint, "__litestar_dependencies__", {}
    )
    return filter_wrapper
