# PyNest Web-Framework-Agnostic Architecture — Phase 1 Design

**Status:** Approved design, ready for implementation.
**Target release:** 0.7.0
**Author:** itay.dar
**Date:** 2026-05-19
**Prior art:** [discussion #99](https://github.com/PythonNest/PyNest/discussions/99), [PR #98](https://github.com/PythonNest/PyNest/pull/98), [PR #100](https://github.com/PythonNest/PyNest/pull/100)

## Goal

Decouple PyNest from FastAPI so the framework can support FastAPI, Litestar, Robyn, and Flask as interchangeable engines under a single PyNest API. **Phase 1 ships the seam with FastAPI as the only adapter.** Future phases add additional engines without touching PyNest core.

## Non-goals (phase 1)

- A second adapter implementation. The seam exists; FastAPI remains the only concrete engine.
- Engine-neutral guards or WebSocket gateways — both stay FastAPI-coupled and are explicitly documented as such.
- Engine-neutral OpenAPI generation. Each adapter delegates to its framework's native generator.
- Making `fastapi` an optional install extra. It remains a main dependency in 0.7.

## Background — how NestJS does it

NestJS exposes `AbstractHttpAdapter<TServer, TRequest, TResponse>` (an abstract class). Two packages — `@nestjs/platform-express` and `@nestjs/platform-fastify` — each ship one concrete adapter. The adapter has two layers:

1. **Concrete pass-through methods** on the base class: `use`, `get/post/put/...`, `listen`, `getHttpServer`. They delegate to `this.instance.<method>(...)` where `instance` is the underlying framework's app object.
2. **Abstract methods** each adapter implements: `reply`, `setHeader`, `getRequestUrl`, `setErrorHandler`, `registerParserMiddleware`, `enableCors`, `createMiddlewareFactory`, `applyVersionFilter`, ~20 in total.

NestJS does **not** define neutral `Request`/`Response` classes. Raw framework objects are passed around and accessed only through adapter methods (`adapter.getRequestUrl(req)`, `adapter.setHeader(res, ...)`).

Critical point: **NestJS itself owns DTO validation, param binding, and OpenAPI generation.** Express and Fastify are used as raw HTTP transports. That's what keeps the adapter surface low-level.

## Why PyNest's adapter is one level higher than NestJS's

PyNest historically **delegates** param parsing, validation, and OpenAPI to FastAPI rather than reimplementing them. A faithful NestJS translation would mean reimplementing huge chunks of FastAPI's runtime inside PyNest core — a 12-month effort that's not justified by phase 1's goal of establishing the seam.

Pragmatic shape: **the adapter accepts a neutral `RouteSpec` and translates it to its framework's native idiom.** FastAPI adapter translates `ParamSpec(source="query", name="page")` to `fastapi.Query(...)` + `Depends(...)`. A future Litestar adapter would translate the same `ParamSpec` to Litestar's `Parameter(query="page")`. The seam stays in one place; PyNest core never imports `fastapi`.

We keep NestJS-style raw-object accessors as a sidecar (`adapter.get_request_method(req)`, `adapter.set_header(res, ...)`) for the few places that need direct req/res access — exception filter wrappers, custom param decorator factories.

## Locked-in decisions

1. **`AbstractHttpAdapter` is an `abc.ABC`** (matches NestJS; shared pass-through behavior lives on the base class).
2. **Single high-level route entry: `adapter.add_route(spec: RouteSpec)`.** RouteSpec carries method, path, endpoint, params, guards, filters, status code, OpenAPI extras.
3. **NestJS-style accessors** on the adapter for raw req/res touchpoints.
4. **`adapter.instance`** is the underlying framework's app object. Exposed via `adapter.get_http_server()` for uvicorn.
5. **`nest.http.Request` / `nest.http.Response`** are type aliases, resolved per-adapter. Under FastAPI default they alias `fastapi.Request` / `fastapi.Response`.
6. **Default adapter is implicit.** `PyNestFactory.create(AppModule)` lazily instantiates `FastAPIAdapter()` — backward-compatible with all 0.6 code.
7. **Layout:** `nest/engine/` (contracts) + `nest/engines/fastapi/` (impl) + `nest/http/` (user-facing facade). FastAPI stays in main deps in phase 1.
8. **Guards and WebSocket gateways remain FastAPI-coupled** in phase 1, explicitly documented as `engines.fastapi`-only.
9. **OpenAPI generation is the adapter's job.** PyNest core does not generate OpenAPI. FastAPI adapter uses FastAPI's native generation.
10. **No breaking changes for 0.6 users.** Ships as 0.7.0.

## Architecture & package layout

```
nest/
├── core/                           # framework-neutral (no fastapi imports)
│   ├── pynest_factory.py           # accepts AbstractHttpAdapter, default FastAPIAdapter
│   ├── pynest_application.py       # holds adapter, not FastAPI
│   └── ...
├── common/
│   ├── route_resolver.py           # walks modules, emits RouteSpecs, calls adapter.add_route
│   ├── decorators.py               # emits neutral ParamSpec; zero fastapi imports
│   └── ...
├── engine/                         # NEW — neutral contracts
│   ├── http_adapter.py             # AbstractHttpAdapter (abc.ABC), NestJS-style
│   ├── params.py                   # ParamSpec dataclass
│   ├── route_spec.py               # RouteSpec dataclass
│   ├── execution_context.py        # ExecutionContext for custom param factories
│   ├── lifespan.py                 # OnStartup / OnShutdown hook protocols
│   └── types.py                    # HttpMethod literal, Endpoint alias
├── engines/                        # NEW — concrete adapters
│   └── fastapi/
│       ├── __init__.py             # exports FastAPIAdapter
│       ├── adapter.py              # FastAPIAdapter(AbstractHttpAdapter)
│       ├── params.py               # ParamSpec → fastapi Depends/Body/Query/Path
│       ├── filters.py              # ExceptionFilter → add_exception_handler
│       └── lifespan.py             # OnStartup/OnShutdown → router.lifespan_context
└── http/                           # NEW — user-facing import facade
    ├── __init__.py                 # re-exports Request, Response, Depends, ...
    └── ...                         # under FastAPI default, these alias fastapi.*
```

## AbstractHttpAdapter contract

```python
# nest/engine/http_adapter.py
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Generic, TypeVar

from nest.engine.route_spec import RouteSpec

TServer = TypeVar("TServer")
TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


class AbstractHttpAdapter(ABC, Generic[TServer, TRequest, TResponse]):
    """Base class for PyNest HTTP engine adapters. NestJS-inspired."""

    def __init__(self, instance: TServer | None = None) -> None:
        self._instance: TServer = instance if instance is not None else self._create_instance()

    # ── server lifecycle ────────────────────────────────────────────────
    @abstractmethod
    def _create_instance(self) -> TServer: ...
    @abstractmethod
    async def close(self) -> None: ...
    def get_http_server(self) -> TServer: return self._instance
    def get_type(self) -> str: return self.__class__.__name__.removesuffix("Adapter").lower()

    # ── route registration (central entry point) ────────────────────────
    @abstractmethod
    def add_route(self, spec: RouteSpec) -> None: ...
    @abstractmethod
    def add_websocket_route(self, path: str, endpoint: Callable[..., Any]) -> None: ...

    # ── middleware / cors ───────────────────────────────────────────────
    @abstractmethod
    def use(self, middleware: Any, **options: Any) -> None: ...
    @abstractmethod
    def enable_cors(self, **options: Any) -> None: ...

    # ── lifecycle hooks ─────────────────────────────────────────────────
    @abstractmethod
    def register_startup_hook(self, fn: Callable[[], Awaitable[None] | None]) -> None: ...
    @abstractmethod
    def register_shutdown_hook(self, fn: Callable[[], Awaitable[None] | None]) -> None: ...

    # ── exception handling ──────────────────────────────────────────────
    @abstractmethod
    def register_exception_handler(
        self, exc_type: type[BaseException], handler: Callable[..., Any],
    ) -> None: ...

    # ── NestJS-style request accessors ──────────────────────────────────
    @abstractmethod
    def get_request_method(self, req: TRequest) -> str: ...
    @abstractmethod
    def get_request_url(self, req: TRequest) -> str: ...
    @abstractmethod
    def get_request_hostname(self, req: TRequest) -> str | None: ...
    @abstractmethod
    def get_request_headers(self, req: TRequest) -> dict[str, str]: ...
    @abstractmethod
    def get_request_client_ip(self, req: TRequest) -> str | None: ...

    # ── NestJS-style response writers ───────────────────────────────────
    @abstractmethod
    def reply(self, res: TResponse, body: Any, status_code: int | None = None) -> Any: ...
    @abstractmethod
    def set_header(self, res: TResponse, name: str, value: str) -> None: ...
    @abstractmethod
    def is_headers_sent(self, res: TResponse) -> bool: ...
    @abstractmethod
    def redirect(self, res: TResponse, url: str, status_code: int = 302) -> Any: ...
```

## RouteSpec and ParamSpec

```python
# nest/engine/route_spec.py
from dataclasses import dataclass, field
from typing import Any, Callable

from nest.engine.params import ParamSpec
from nest.engine.types import HttpMethod


@dataclass(frozen=True)
class RouteSpec:
    method: HttpMethod
    path: str
    endpoint: Callable[..., Any]
    params: tuple[ParamSpec, ...] = ()
    guards: tuple[Any, ...] = ()
    filters: tuple[Any, ...] = ()
    status_code: int | None = None
    tags: tuple[str, ...] = ()
    name: str | None = None
    summary: str | None = None
    description: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
```

```python
# nest/engine/params.py
from dataclasses import dataclass
from typing import Any, Callable, Literal

ParamSource = Literal[
    "body", "query", "path", "header",
    "request", "response", "ip", "host", "custom",
]


@dataclass(frozen=True)
class ParamSpec:
    source: ParamSource
    name: str | None = None
    annotation: Any = None
    default: Any = ...                                  # `...` means required
    pipes: tuple[Any, ...] = ()
    factory: Callable[[Any, Any], Any] | None = None    # for custom factories
    data: Any = None                                    # custom-factory metadata
```

## Param decorator translation

User-facing API is unchanged:

```python
from nest.common.decorators import Body, Query, Param, Headers, Req, Res

@Controller("/users")
class UserController:
    @Get("/{id}")
    def show(
        self,
        id: int = Param("id"),
        verbose: bool = Query("verbose", default=False),
        auth: str = Headers("Authorization"),
    ): ...
```

What changes: the decorators return neutral `ParamSpec` objects instead of FastAPI-aware metadata.

```python
# nest/common/decorators.py (refactored — zero fastapi imports)
from nest.engine.params import ParamSpec


def Body(key=None, *pipes, default=...):
    name, pipes = _normalize(key, pipes)
    return ParamSpec(source="body", name=name, default=default, pipes=tuple(pipes))


def Query(name=None, *pipes, default=...):
    name, pipes = _normalize(name, pipes)
    return ParamSpec(source="query", name=name, default=default, pipes=tuple(pipes))


# ... same shape for Param, Headers, Req, Res, Ip, HostParam, createParamDecorator
```

The translation logic (today's ~250 lines in `_build_dependency`/`_dependency_signature`) moves into `nest/engines/fastapi/params.py`. Same algorithm, new home — but now it's replaceable per adapter.

## Migration of core files

### pynest_factory.py

```python
class PyNestFactory:
    @staticmethod
    def create(
        main_module,
        adapter: AbstractHttpAdapter | None = None,
        **kwargs,
    ) -> PyNestApp:
        container = PyNestContainer()
        container.add_module(main_module)
        container.build()
        PyNestFactory._run_async(container.initialize_lifecycle())

        if adapter is None:
            from nest.engines.fastapi import FastAPIAdapter
            adapter = FastAPIAdapter(**kwargs)
        elif kwargs:
            raise TypeError(
                "Pass FastAPI/Litestar kwargs to the adapter constructor, "
                "not to PyNestFactory.create() when adapter= is set."
            )
        return PyNestApp(container, adapter)
```

### pynest_application.py

```python
class PyNestApp:
    def __init__(self, container, adapter: AbstractHttpAdapter) -> None:
        self.container = container
        self.adapter = adapter
        self._install_lifespan_shutdown()
        RoutesResolver(self.container, self.adapter).register_routes()

    @property
    def http_server(self):
        """Deprecated — prefer adapter.get_http_server(). Kept for 0.6 compatibility."""
        return self.adapter.get_http_server()

    def get_server(self): return self.adapter.get_http_server()
    def get_http_server(self): return self.adapter.get_http_server()

    def use(self, middleware, **options):
        self.adapter.use(middleware, **options)
        return self

    def use_global_filters(self, *filters):
        for f in filters:
            for exc_type in getattr(f, "__caught_exceptions__", None) or (Exception,):
                self.adapter.register_exception_handler(
                    exc_type, _make_filter_handler(f, self.adapter),
                )
        return self

    def _install_lifespan_shutdown(self):
        self.adapter.register_shutdown_hook(self.close)
```

### route_resolver.py

```python
def __init__(self, container, adapter: AbstractHttpAdapter):
    self.container = container
    self.adapter = adapter

def _register_controller(self, cls):
    instance = self.container.get_controller_instance(cls)
    prefix = getattr(cls, "__route_prefix__", None) or ""
    tag = getattr(cls, "__controller_tag__", None)
    for name, unbound in inspect.getmembers(cls, predicate=callable):
        http_method = getattr(unbound, "__http_method__", None)
        if not isinstance(http_method, HTTPMethod):
            continue
        spec = RouteSpec(
            method=http_method,
            path=_join_paths(prefix, getattr(unbound, "__route_path__", "/")),
            endpoint=getattr(instance, name),
            params=_extract_params(unbound),
            guards=tuple(_collect_guards(cls, unbound)),
            filters=tuple(
                getattr(unbound, "__filters__", [])
                + getattr(cls, "__filters__", [])
            ),
            status_code=getattr(unbound, "status_code", None),
            tags=(tag,) if tag else (),
            extra=getattr(unbound, "__kwargs__", {}),
        )
        self.adapter.add_route(spec)
```

## Backward compatibility contract (0.7.0)

Guaranteed to keep working byte-for-byte:

- `PyNestFactory.create(AppModule, **fastapi_kwargs)` — kwargs flow into implicit `FastAPIAdapter`.
- `app.http_server`, `app.get_server()`, `app.get_http_server()` — return the `FastAPI` instance.
- `app.use(MiddlewareClass, **opts)`, `app.use_global_filters(...)`, `app.enable_shutdown_hooks()`, `await app.close()`.
- All user imports: `from fastapi import Request, Response, Depends, HTTPException`.
- `BaseGuard`, `UseGuards`, security_schemes (documented as `engines.fastapi` features in phase 1).
- WebSocket gateways (documented as `engines.fastapi` features).

New API (additive, non-breaking):

- `PyNestFactory.create(AppModule, adapter=FastAPIAdapter(...))`.
- `from nest.http import Request, Response` (aliases `fastapi.*`).
- `nest.engine.AbstractHttpAdapter` is public API.

Deprecation timeline: 0.7.0 ships with no deprecation warnings. 0.7.1 introduces warnings on `app.http_server` and `from fastapi import ...` in PyNest application code. 1.0 removes the shims.

## Testing strategy

### Layer 1 — existing suite as regression net

The current 34 test files must pass byte-identically with zero test edits between PR 1 and PR 3. CI gate: `uv run pytest tests/` green. Any required test edit is grounds to rework the migration approach.

The only allowed exception is a handful of internal-only tests asserting private wiring (e.g. `self.app_ref is FastAPI`). These are explicitly called out in the PR.

### Layer 2 — adapter conformance suite

New: `tests/test_engine/conformance/`. Pytest-parametrized across every registered adapter. In phase 1, only FastAPI. Phase 2 adds one line to the fixture list.

```
tests/test_engine/
├── conformance/
│   ├── conftest.py                   # parametrized adapter fixture
│   ├── test_route_registration.py
│   ├── test_param_binding.py
│   ├── test_request_accessors.py
│   ├── test_response_accessors.py
│   ├── test_middleware.py
│   ├── test_exception_handlers.py
│   ├── test_lifespan.py
│   └── test_cors.py
└── unit/
    ├── test_route_spec.py
    ├── test_param_spec.py
    └── test_http_adapter_base.py
```

### Layer 3 — adapter-internal unit tests

`tests/test_engines/test_fastapi/` — translation logic that doesn't fit conformance (e.g. `ParamSpec → fastapi.Query` marker shape, guard → `Security(...)` translation, lifespan wiring).

### CI changes

- Matrix dimension `adapter: [fastapi]` so conformance suite is explicit in CI output.
- Coverage gate: `nest/engine/` and `nest/engines/fastapi/` ≥90% line coverage.
- Grep gate: no `from fastapi` / `import fastapi` in `nest/core/` or `nest/common/` (only in `nest/engines/fastapi/`, `nest/http/`, and phase-1-coupled `nest/websockets/` + `nest/core/decorators/guards.py`).
- OpenAPI drift gate: generate `/openapi.json` from a reference app pre- and post-cutover, fail on non-empty diff.
- Perf gate: 1k-request micro-benchmark, fail PR 3 if P99 regresses >5%.

### Quality gates for 0.7.0

1. Full existing suite green, zero behavioral test edits.
2. Conformance suite green for FastAPI.
3. Per-adapter unit tests green.
4. ≥90% line coverage on `nest/engine/` and `nest/engines/fastapi/`.
5. Manual smoke: all 6 `examples/` projects run unchanged.
6. Manual smoke: freshly-generated `pynest generate application` builds + serves; `/docs` renders; OpenAPI is byte-identical to 0.6.

## Documentation plan

### New pages

| File | Audience |
|------|----------|
| `docs/engine/overview.md` | Every user. Why engine adapters exist (NestJS analogy), wiring diagram, feature matrix across engines. |
| `docs/engine/fastapi_adapter.md` | FastAPI users. `FastAPIAdapter` constructor kwargs, FastAPI-specific features (guard security schemes, raw WS gateways), what changed vs. 0.6. |
| `docs/engine/writing_an_adapter.md` | Contributors. Every abstract method explained, conformance suite as the gate, worked example pseudocode for a Litestar adapter. |
| `docs/engine/migration_0.7.md` | Upgraders. TL;DR, what's new, what's deprecated, what's unchanged, known limitations of phase 1. |

### Existing pages, surgical edits

- `introduction.md` — one paragraph on engine abstraction, link to overview.
- `getting_started.md` — small "Choosing an engine" subsection.
- `controllers.md`, `param_decorators.md` — recommend `from nest.http import ...` over `from fastapi import ...`; note FastAPI imports still work.
- `guards.md` — banner: phase-1 FastAPI-only feature.
- `websockets.md` — banner: phase-1 FastAPI-only feature.

### mkdocs.yml nav

```yaml
nav:
  - Overview: ...
  - Engine:
      - Overview: engine/overview.md
      - FastAPI Adapter: engine/fastapi_adapter.md
      - Writing an Adapter: engine/writing_an_adapter.md
      - Migration to 0.7: engine/migration_0.7.md
  - Dependency Injection: ...
  - ...
```

## Milestones (PR sequence)

| # | Branch | Acceptance | Est. size |
|---|--------|-----------|-----------|
| 1 | `engine/contracts` | `AbstractHttpAdapter`, `RouteSpec`, `ParamSpec`, `HttpMethod`, `nest/http/` facade. Dataclass unit tests green. No callers yet. | ~400 LOC + ~150 test LOC |
| 2 | `engine/fastapi-adapter` | `nest/engines/fastapi/` complete. Conformance suite green. Per-adapter unit tests green. Not yet integrated. | ~600 LOC + ~500 test LOC |
| 3 | `engine/cutover` | `PyNestFactory`, `PyNestApp`, `RoutesResolver`, `nest/common/decorators.py` rewritten. **Existing 34-file suite green with zero behavioral edits.** Compat shims in place. All `examples/` smoke-clean. | ~500 LOC delta |
| 4 | `engine/docs` | 4 new doc pages, mkdocs nav, CHANGELOG, `[project.optional-dependencies] fastapi` extras declared. | ~400 LOC docs |

PRs 1, 2, 4 are independently mergeable. PR 3 is the cutover and gates the 0.7.0 release.

## Risks and mitigations

| Risk | Mitigation |
|------|-----------|
| Param translation regression (a `@Body`/`@Query`/`@Param` edge case behaves differently) | Existing `tests/test_common/test_param_decorators.py` is regression net. Conformance suite re-tests from clean angle. |
| OpenAPI output drifts (path params, descriptions, security schemes render differently) | CI: pre/post `diff` of `/openapi.json` from a reference app. Fail PR 3 on non-empty diff. |
| Lifespan ordering changes | Existing `tests/test_core/test_lifecycle_hooks.py`. Plus new conformance lifespan test asserts ordering. |
| Guard `security_scheme` integration breaks (Swagger "Authorize" stops working) | Guards stay FastAPI-coupled in phase 1; `guard.as_dependency()` → `Security(...)` preserved verbatim inside `FastAPIAdapter.add_route()`. |
| WebSocket gateway registration changes | `adapter.add_websocket_route(...)` is a thin delegate. `tests/test_websockets/` is the gate. |
| Performance regression from extra indirection | 1k-request micro-benchmark in CI. Fail if P99 regresses >5%. |
| Hidden `from fastapi` left in `nest/core` or `nest/common` | CI grep gate. |

## Out of scope (deferred)

- Litestar / Robyn / Flask adapters (phase 2+).
- Engine-neutral guards (lift `BaseGuard` off `fastapi.Request`, reimplement `security_scheme` per-adapter). Phase 2.
- Engine-neutral WebSocket gateway protocol. Phase 2.
- Engine-neutral OpenAPI generation. Likely never — delegate to each framework's native generator.
- `fastapi` as an optional install extra rather than a main dep. Phase 2 when a real second engine exists.
- Deprecation warnings on `from fastapi import …` or `app.http_server`. 0.7.1.

## Open questions

None blocking. Implementation can start on PR 1.
