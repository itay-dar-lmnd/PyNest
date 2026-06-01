"""
Blacksheep implementation of AbstractHttpAdapter.

Blacksheep's DI is Rodi (resolves by type annotation) and can't consume PyNest's
ParamSpec model, so this adapter uses the "request-extraction wrapper" approach:
every route is registered as ``async def handler(request)`` and the wrapper runs
guards → param extraction → handler → exception filters → serialization itself.
Blacksheep still owns routing, middleware, lifecycle, OpenAPI, and WebSockets.

User code (guards, custom param factories, controllers) is written against the
Starlette-shaped ``nest.http.Request``; Blacksheep's native request differs, so
the wrapper hands user code a ``StarletteCompatRequest`` facade.
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Optional

from blacksheep import Application, Request, Response
from blacksheep import json as bs_json
from blacksheep import (
    moved_permanently,
    permanent_redirect,
    redirect,
    see_other,
    temporary_redirect,
)

from nest.engine._shared import NO_FILTER_MATCH
from nest.engine._shared import extract_credentials as _extract_credentials
from nest.engine._shared import run_filters
from nest.engine.http_adapter import AbstractHttpAdapter
from nest.engine.route_spec import RouteSpec
from nest.engine.types import HttpMethod
from nest.engines.blacksheep.compat import (
    StarletteCompatRequest,
    StarletteCompatWebSocket,
)
from nest.engines.blacksheep.params import build_param_plan, extract_params
from nest.engines.blacksheep.serialize import serialize, to_blacksheep_response

# HttpMethod → Blacksheep Router registration method name.
_METHOD_MAP = {
    HttpMethod.GET: "add_get",
    HttpMethod.POST: "add_post",
    HttpMethod.PUT: "add_put",
    HttpMethod.PATCH: "add_patch",
    HttpMethod.DELETE: "add_delete",
    HttpMethod.HEAD: "add_head",
    HttpMethod.OPTIONS: "add_options",
}

# status_code → Blacksheep redirect helper (none accept a custom status).
_REDIRECT_MAP = {
    301: moved_permanently,
    302: redirect,
    303: see_other,
    307: temporary_redirect,
    308: permanent_redirect,
}


class BlacksheepAdapter(AbstractHttpAdapter[Application, Request, Response]):
    """
    PyNest's Blacksheep engine adapter. Wraps a Blacksheep ``Application``.

    Construct with no args, with ``title``/``version``/``description`` (forwarded
    to the OpenAPI docs), or with ``instance=`` to wrap an existing Application.
    """

    def __init__(
        self,
        instance: Optional[Application] = None,
        *,
        title: str = "PyNest App",
        version: str = "0.7.0",
        description: str = "Built with PyNest",
        show_error_details: bool = False,
        **kwargs: Any,
    ) -> None:
        self._title = title
        self._version = version
        self._description = description
        self._show_error_details = show_error_details
        self._extra_kwargs = kwargs
        self._docs = None
        super().__init__(instance)

    # ── server lifecycle ────────────────────────────────────────────────

    def _create_instance(self) -> Application:
        # Blacksheep's Application() falls back to a *module-level global* router
        # when none is passed — so two apps in one process (e.g. main.py's
        # import-time app + a test fixture's app) would share it and register
        # every route twice, colliding at start(). Give each app its own Router.
        from blacksheep.server.routing import Router

        app = Application(
            router=Router(),
            show_error_details=self._show_error_details,
            **self._extra_kwargs,
        )
        # Mount OpenAPI/Swagger so /docs and /openapi.json exist (FastAPI parity).
        from blacksheep.server.openapi.v3 import OpenAPIHandler
        from openapidocs.v3 import Info

        self._docs = OpenAPIHandler(
            info=Info(
                title=self._title,
                version=self._version,
                description=self._description,
            ),
            ui_path="/docs",
            json_spec_path="/openapi.json",
        )
        self._docs.bind_app(app)
        return app

    async def close(self) -> None:
        return None

    # ── route registration (central entry point) ────────────────────────

    def add_route(self, spec: RouteSpec) -> None:
        original = spec.endpoint
        plan = build_param_plan(original)
        guards = spec.guards
        filters = spec.filters
        status_code = spec.status_code

        async def handler(request: Request) -> Response:
            facade = StarletteCompatRequest(request)

            # 1. Guards — before anything else.
            for guard in guards:
                g = guard() if inspect.isclass(guard) else guard
                credentials = None
                if getattr(g, "security_scheme", None) is not None:
                    credentials = _extract_credentials(facade, g.security_scheme)
                ok = g.can_activate(facade, credentials)
                if inspect.isawaitable(ok):
                    ok = await ok
                if not ok:
                    return bs_json(
                        {"detail": "Access denied: insufficient permissions"},
                        status=403,
                    )

            # 2. Resolve params from the request.
            kwargs = await extract_params(facade, plan)

            # 3. Call the handler, routing exceptions through filters.
            try:
                result = original(**kwargs)
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:
                handled = await run_filters(
                    exc, facade, filters, convert=to_blacksheep_response
                )
                if handled is NO_FILTER_MATCH:
                    raise
                return handled if handled is not None else bs_json(None, status=204)

            # 4. Serialize.
            return serialize(result, status_code)

        handler.__name__ = getattr(original, "__name__", "blacksheep_handler")
        self._apply_docs(handler, spec)

        register = getattr(self._instance.router, _METHOD_MAP[spec.method])
        register(spec.path, handler)

    def _apply_docs(self, handler: Callable, spec: RouteSpec) -> None:
        """Attach OpenAPI metadata via Blacksheep's docs decorator (instance call)."""
        if self._docs is None:
            return
        from blacksheep.server.openapi.common import ResponseInfo

        self._docs(
            summary=spec.summary,
            description=spec.description,
            tags=list(spec.tags) if spec.tags else None,
            responses={spec.status_code or 200: ResponseInfo("Success")},
        )(handler)

    def add_websocket_route(self, path: str, endpoint: Callable[..., Any]) -> None:
        async def bs_endpoint(websocket) -> None:
            await endpoint(StarletteCompatWebSocket(websocket))

        self._instance.router.add_ws(path, bs_endpoint)

    # ── middleware / CORS ───────────────────────────────────────────────

    def use(self, middleware: Any, **options: Any) -> None:
        # Blacksheep middleware is ``async def mw(request, handler) -> Response``.
        # Starlette/FastAPI class middleware is not portable here.
        self._instance.middlewares.append(middleware)

    def enable_cors(self, **options: Any) -> None:
        self._instance.use_cors(
            allow_methods=options.get("allow_methods", "*"),
            allow_origins=options.get("allow_origins", "*"),
            allow_headers=options.get("allow_headers", "*"),
            allow_credentials=options.get("allow_credentials", False),
        )

    # ── lifecycle hooks ─────────────────────────────────────────────────

    def register_startup_hook(self, fn: Callable[[], Any]) -> None:
        async def _hook(app: Application) -> None:
            result = fn()
            if inspect.isawaitable(result):
                await result

        self._instance.on_start += _hook

    def register_shutdown_hook(self, fn: Callable[[], Any]) -> None:
        async def _hook(app: Application) -> None:
            result = fn()
            if inspect.isawaitable(result):
                await result

        self._instance.on_stop += _hook

    # ── exception handling ──────────────────────────────────────────────

    def register_exception_handler(
        self,
        exc_type: type,
        handler: Callable[..., Any],
    ) -> None:
        # Blacksheep requires async handlers with exactly (app, request, exc).
        # PyNest's handler may be sync and may return a Starlette JSONResponse,
        # so wrap async and convert the response.
        async def _bs_handler(app: Application, request: Request, exc: Exception):
            result = handler(StarletteCompatRequest(request), exc)
            if inspect.isawaitable(result):
                result = await result
            converted = to_blacksheep_response(result)
            return converted if converted is not None else bs_json(None, status=500)

        self._instance.exceptions_handlers[exc_type] = _bs_handler

    # ── NestJS-style request accessors ──────────────────────────────────

    def get_request_method(self, req: Any) -> str:
        return req.method

    def get_request_url(self, req: Any) -> str:
        return str(req.url)

    def get_request_hostname(self, req: Any) -> Optional[str]:
        host = getattr(req, "host", None)
        return host.split(":")[0] if host else None

    def get_request_headers(self, req: Any) -> dict:
        return dict(req.headers.items())

    def get_request_client_ip(self, req: Any) -> Optional[str]:
        client = getattr(req, "client", None)
        return client.host if client else None

    # ── NestJS-style response writers ───────────────────────────────────

    def reply(self, res: Any, body: Any, status_code: Optional[int] = None) -> Any:
        return bs_json(body, status=status_code or 200)

    def set_header(self, res: Any, name: str, value: str) -> None:
        res.add_header(name.encode(), value.encode())

    def is_headers_sent(self, res: Any) -> bool:
        return False

    def redirect(self, res: Any, url: str, status_code: int = 302) -> Any:
        helper = _REDIRECT_MAP.get(status_code)
        if helper is not None:
            return helper(url)
        return Response(status_code, [(b"location", url.encode())])
