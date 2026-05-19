# PR 1: Engine Contracts — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `nest/engine/` (neutral contracts) and `nest/http/` (user-facing facade) with zero changes to any existing caller — purely additive.

**Architecture:** `AbstractHttpAdapter` (abc.ABC) defines the contract every engine must satisfy. `RouteSpec` and `ParamSpec` are frozen dataclasses that carry route/parameter metadata between PyNest core and adapters in a framework-neutral way. `nest/http/` re-exports framework types so user code has a stable import surface. Nothing in `nest/core/` or `nest/common/` is touched in this PR.

**Tech Stack:** Python 3.9+ (use `from __future__ import annotations` everywhere), `abc`, `dataclasses`, `pytest`.

---

## Task 1: `nest/engine/types.py` — shared type aliases

**Files:**
- Create: `nest/engine/__init__.py`
- Create: `nest/engine/types.py`
- Create: `tests/test_engine/__init__.py`
- Create: `tests/test_engine/unit/__init__.py`
- Create: `tests/test_engine/unit/test_types.py`

**Step 1: Write the failing test**

```python
# tests/test_engine/unit/test_types.py
from __future__ import annotations

def test_http_method_values():
    from nest.engine.types import HttpMethod
    assert HttpMethod.GET.value == "GET"
    assert HttpMethod.POST.value == "POST"
    assert HttpMethod.DELETE.value == "DELETE"
    assert HttpMethod.PUT.value == "PUT"
    assert HttpMethod.PATCH.value == "PATCH"
    assert HttpMethod.HEAD.value == "HEAD"
    assert HttpMethod.OPTIONS.value == "OPTIONS"

def test_endpoint_is_callable_alias():
    from nest.engine.types import Endpoint
    import typing
    # Endpoint is just a type alias — verify it's importable and is a type form
    assert Endpoint is not None
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_engine/unit/test_types.py -v
```
Expected: `ModuleNotFoundError: No module named 'nest.engine'`

**Step 3: Create the files**

```python
# nest/engine/__init__.py
```

```python
# nest/engine/types.py
from __future__ import annotations

from typing import Any, Callable

# Re-export HTTPMethod from its existing home to avoid duplication.
# In a future PR (PR 3) route_resolver.py will import HttpMethod from here.
from nest.core.decorators.http_method import HTTPMethod as HttpMethod

Endpoint = Callable[..., Any]

__all__ = ["HttpMethod", "Endpoint"]
```

```python
# tests/test_engine/__init__.py
```

```python
# tests/test_engine/unit/__init__.py
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_engine/unit/test_types.py -v
```
Expected: `2 passed`

**Step 5: Commit**

```bash
git add nest/engine/__init__.py nest/engine/types.py \
        tests/test_engine/__init__.py tests/test_engine/unit/__init__.py \
        tests/test_engine/unit/test_types.py
git commit -m "feat(engine): add nest/engine/types.py — HttpMethod re-export and Endpoint alias"
```

---

## Task 2: `nest/engine/params.py` — ParamSpec dataclass

**Files:**
- Create: `nest/engine/params.py`
- Create: `tests/test_engine/unit/test_param_spec.py`

**Step 1: Write the failing test**

```python
# tests/test_engine/unit/test_param_spec.py
from __future__ import annotations

import pytest


def test_paramspec_defaults():
    from nest.engine.params import ParamSpec
    p = ParamSpec(source="query")
    assert p.source == "query"
    assert p.name is None
    assert p.annotation is None
    assert p.default is ...
    assert p.pipes == ()
    assert p.factory is None
    assert p.data is None


def test_paramspec_is_frozen():
    from nest.engine.params import ParamSpec
    p = ParamSpec(source="body", name="payload")
    with pytest.raises((AttributeError, TypeError)):
        p.name = "other"  # type: ignore[misc]


def test_paramspec_all_sources_valid():
    from nest.engine.params import ParamSpec, VALID_SOURCES
    for src in VALID_SOURCES:
        p = ParamSpec(source=src)
        assert p.source == src


def test_paramspec_with_pipes():
    from nest.engine.params import ParamSpec

    def trim(v):
        return v.strip()

    p = ParamSpec(source="query", name="q", pipes=(trim,))
    assert p.pipes == (trim,)


def test_paramspec_with_default():
    from nest.engine.params import ParamSpec
    p = ParamSpec(source="query", name="page", default=1)
    assert p.default == 1


def test_paramspec_with_custom_factory():
    from nest.engine.params import ParamSpec

    def my_factory(data, ctx):
        return "value"

    p = ParamSpec(source="custom", factory=my_factory, data={"key": "val"})
    assert p.factory is my_factory
    assert p.data == {"key": "val"}
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_engine/unit/test_param_spec.py -v
```
Expected: `ModuleNotFoundError: No module named 'nest.engine.params'`

**Step 3: Implement**

```python
# nest/engine/params.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Tuple

VALID_SOURCES = (
    "body",
    "query",
    "path",
    "header",
    "request",
    "response",
    "ip",
    "host",
    "custom",
)

_MISSING = object()


@dataclass(frozen=True)
class ParamSpec:
    source: str
    name: Optional[str] = None
    annotation: Any = None
    default: Any = ...
    pipes: Tuple[Any, ...] = ()
    factory: Optional[Callable[[Any, Any], Any]] = None
    data: Any = None

    def __post_init__(self) -> None:
        if self.source not in VALID_SOURCES:
            raise ValueError(
                f"Invalid param source {self.source!r}. "
                f"Must be one of: {VALID_SOURCES}"
            )

__all__ = ["ParamSpec", "VALID_SOURCES"]
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_engine/unit/test_param_spec.py -v
```
Expected: `6 passed`

**Step 5: Commit**

```bash
git add nest/engine/params.py tests/test_engine/unit/test_param_spec.py
git commit -m "feat(engine): add ParamSpec dataclass — neutral parameter source descriptor"
```

---

## Task 3: `nest/engine/route_spec.py` — RouteSpec dataclass

**Files:**
- Create: `nest/engine/route_spec.py`
- Create: `tests/test_engine/unit/test_route_spec.py`

**Step 1: Write the failing test**

```python
# tests/test_engine/unit/test_route_spec.py
from __future__ import annotations

import pytest


def _make_endpoint():
    async def endpoint():
        return {"ok": True}
    return endpoint


def test_routespec_minimal():
    from nest.engine.route_spec import RouteSpec
    from nest.engine.types import HttpMethod
    ep = _make_endpoint()
    spec = RouteSpec(method=HttpMethod.GET, path="/", endpoint=ep)
    assert spec.method == HttpMethod.GET
    assert spec.path == "/"
    assert spec.endpoint is ep
    assert spec.params == ()
    assert spec.guards == ()
    assert spec.filters == ()
    assert spec.status_code is None
    assert spec.tags == ()
    assert spec.name is None
    assert spec.summary is None
    assert spec.description is None
    assert spec.extra == {}


def test_routespec_is_frozen():
    from nest.engine.route_spec import RouteSpec
    from nest.engine.types import HttpMethod
    ep = _make_endpoint()
    spec = RouteSpec(method=HttpMethod.POST, path="/items", endpoint=ep)
    with pytest.raises((AttributeError, TypeError)):
        spec.path = "/other"  # type: ignore[misc]


def test_routespec_with_params():
    from nest.engine.route_spec import RouteSpec
    from nest.engine.params import ParamSpec
    from nest.engine.types import HttpMethod
    ep = _make_endpoint()
    p = ParamSpec(source="query", name="page", default=1)
    spec = RouteSpec(
        method=HttpMethod.GET, path="/items", endpoint=ep, params=(p,)
    )
    assert spec.params == (p,)


def test_routespec_extra_is_independent_per_instance():
    from nest.engine.route_spec import RouteSpec
    from nest.engine.types import HttpMethod
    ep = _make_endpoint()
    spec1 = RouteSpec(method=HttpMethod.GET, path="/a", endpoint=ep)
    spec2 = RouteSpec(method=HttpMethod.GET, path="/b", endpoint=ep)
    assert spec1.extra is not spec2.extra


def test_routespec_full():
    from nest.engine.route_spec import RouteSpec
    from nest.engine.params import ParamSpec
    from nest.engine.types import HttpMethod
    ep = _make_endpoint()
    p = ParamSpec(source="body", name="data")
    spec = RouteSpec(
        method=HttpMethod.POST,
        path="/users",
        endpoint=ep,
        params=(p,),
        status_code=201,
        tags=("users",),
        name="create_user",
        summary="Create a user",
        description="Creates a new user record.",
        extra={"response_model_exclude_none": True},
    )
    assert spec.status_code == 201
    assert spec.tags == ("users",)
    assert spec.name == "create_user"
    assert spec.extra == {"response_model_exclude_none": True}
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_engine/unit/test_route_spec.py -v
```
Expected: `ModuleNotFoundError: No module named 'nest.engine.route_spec'`

**Step 3: Implement**

```python
# nest/engine/route_spec.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

from nest.engine.params import ParamSpec
from nest.engine.types import HttpMethod


@dataclass(frozen=True)
class RouteSpec:
    method: HttpMethod
    path: str
    endpoint: Callable[..., Any]
    params: Tuple[ParamSpec, ...] = ()
    guards: Tuple[Any, ...] = ()
    filters: Tuple[Any, ...] = ()
    status_code: Optional[int] = None
    tags: Tuple[str, ...] = ()
    name: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

__all__ = ["RouteSpec"]
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_engine/unit/test_route_spec.py -v
```
Expected: `5 passed`

**Step 5: Commit**

```bash
git add nest/engine/route_spec.py tests/test_engine/unit/test_route_spec.py
git commit -m "feat(engine): add RouteSpec dataclass — neutral route descriptor"
```

---

## Task 4: `nest/engine/execution_context.py` — framework-neutral ExecutionContext

**Files:**
- Create: `nest/engine/execution_context.py`
- Create: `tests/test_engine/unit/test_execution_context.py`

**Note:** The existing `ExecutionContext` in `nest/common/decorators.py` wraps `fastapi.Request` directly. This new one is framework-neutral — it holds raw objects and exposes them via simple getters. In PR 3, the `createParamDecorator` factory will receive one of these. The existing `ExecutionContext` is **not deleted** in this PR.

**Step 1: Write the failing test**

```python
# tests/test_engine/unit/test_execution_context.py
from __future__ import annotations


def test_execution_context_http():
    from nest.engine.execution_context import ExecutionContext

    sentinel_req = object()
    sentinel_res = object()
    ctx = ExecutionContext(request=sentinel_req, response=sentinel_res)

    http = ctx.switch_to_http()
    assert http.get_request() is sentinel_req
    assert http.get_response() is sentinel_res


def test_execution_context_get_type():
    from nest.engine.execution_context import ExecutionContext
    ctx = ExecutionContext(request=object())
    assert ctx.get_type() == "http"


def test_execution_context_response_optional():
    from nest.engine.execution_context import ExecutionContext
    ctx = ExecutionContext(request=object())
    http = ctx.switch_to_http()
    assert http.get_response() is None


def test_http_execution_context_standalone():
    from nest.engine.execution_context import HttpExecutionContext
    req = object()
    http = HttpExecutionContext(request=req)
    assert http.get_request() is req
    assert http.get_response() is None
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_engine/unit/test_execution_context.py -v
```
Expected: `ModuleNotFoundError: No module named 'nest.engine.execution_context'`

**Step 3: Implement**

```python
# nest/engine/execution_context.py
from __future__ import annotations

from typing import Any, Optional


class HttpExecutionContext:
    def __init__(self, request: Any, response: Optional[Any] = None) -> None:
        self._request = request
        self._response = response

    def get_request(self) -> Any:
        return self._request

    def get_response(self) -> Optional[Any]:
        return self._response


class ExecutionContext:
    def __init__(self, request: Any, response: Optional[Any] = None) -> None:
        self._request = request
        self._response = response

    def switch_to_http(self) -> HttpExecutionContext:
        return HttpExecutionContext(self._request, self._response)

    def get_type(self) -> str:
        return "http"


__all__ = ["ExecutionContext", "HttpExecutionContext"]
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_engine/unit/test_execution_context.py -v
```
Expected: `4 passed`

**Step 5: Commit**

```bash
git add nest/engine/execution_context.py \
        tests/test_engine/unit/test_execution_context.py
git commit -m "feat(engine): add framework-neutral ExecutionContext"
```

---

## Task 5: `nest/engine/http_adapter.py` — AbstractHttpAdapter ABC

**Files:**
- Create: `nest/engine/http_adapter.py`
- Create: `tests/test_engine/unit/test_http_adapter_base.py`

**Step 1: Write the failing test**

```python
# tests/test_engine/unit/test_http_adapter_base.py
from __future__ import annotations

import pytest


class _MinimalAdapter:
    """Concrete stub that satisfies every abstract method for testing the base class."""
    def _create_instance(self): return object()
    async def close(self): pass
    def add_route(self, spec): pass
    def add_websocket_route(self, path, endpoint): pass
    def use(self, middleware, **opts): pass
    def enable_cors(self, **opts): pass
    def register_startup_hook(self, fn): pass
    def register_shutdown_hook(self, fn): pass
    def register_exception_handler(self, exc_type, handler): pass
    def get_request_method(self, req): return "GET"
    def get_request_url(self, req): return "/test"
    def get_request_hostname(self, req): return "localhost"
    def get_request_headers(self, req): return {}
    def get_request_client_ip(self, req): return "127.0.0.1"
    def reply(self, res, body, status_code=None): pass
    def set_header(self, res, name, value): pass
    def is_headers_sent(self, res): return False
    def redirect(self, res, url, status_code=302): pass


def _build_minimal_class():
    from nest.engine.http_adapter import AbstractHttpAdapter
    # Dynamically attach base to satisfy ABC
    cls = type("MinimalAdapter", (AbstractHttpAdapter, _MinimalAdapter), {})
    return cls


def test_abstract_adapter_cannot_be_instantiated_directly():
    from nest.engine.http_adapter import AbstractHttpAdapter
    with pytest.raises(TypeError):
        AbstractHttpAdapter()  # type: ignore[abstract]


def test_concrete_adapter_requires_all_abstract_methods():
    from nest.engine.http_adapter import AbstractHttpAdapter

    class Incomplete(AbstractHttpAdapter):
        def _create_instance(self): return object()
        # missing all other abstract methods

    with pytest.raises(TypeError):
        Incomplete()


def test_get_http_server_returns_instance():
    cls = _build_minimal_class()
    adapter = cls()
    server = adapter.get_http_server()
    assert server is not None


def test_get_type_strips_adapter_suffix():
    cls = _build_minimal_class()
    adapter = cls()
    # Class is named "MinimalAdapter" → type is "minimal"
    assert adapter.get_type() == "minimal"


def test_get_type_default_no_suffix():
    from nest.engine.http_adapter import AbstractHttpAdapter

    class MyEngine(AbstractHttpAdapter, _MinimalAdapter):
        pass

    adapter = MyEngine()
    assert adapter.get_type() == "myengine"


def test_adapter_instance_passthrough():
    """If instance is provided in constructor, get_http_server returns it."""
    from nest.engine.http_adapter import AbstractHttpAdapter

    sentinel = object()

    class Provided(AbstractHttpAdapter, _MinimalAdapter):
        pass

    adapter = Provided(instance=sentinel)
    assert adapter.get_http_server() is sentinel
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_engine/unit/test_http_adapter_base.py -v
```
Expected: `ModuleNotFoundError: No module named 'nest.engine.http_adapter'`

**Step 3: Implement**

```python
# nest/engine/http_adapter.py
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Generic, Optional, TypeVar

from nest.engine.route_spec import RouteSpec

TServer = TypeVar("TServer")
TRequest = TypeVar("TRequest")
TResponse = TypeVar("TResponse")


class AbstractHttpAdapter(ABC, Generic[TServer, TRequest, TResponse]):
    """
    Base class for PyNest HTTP engine adapters.

    Wraps a web framework instance and exposes a neutral API for:
    - Route registration (add_route)
    - Middleware and CORS
    - Startup/shutdown lifecycle hooks
    - Exception handling
    - Request accessor methods (NestJS-style raw-object accessors)
    - Response writer methods

    Inspired by NestJS AbstractHttpAdapter. Key difference from NestJS:
    add_route() accepts a full RouteSpec (including param bindings, guards,
    filters) because PyNest delegates validation/OpenAPI to the framework
    rather than reimplementing them in core.
    """

    def __init__(self, instance: Optional[Any] = None) -> None:
        self._instance: Any = instance if instance is not None else self._create_instance()

    # ── concrete helpers (no override needed) ──────────────────────────
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
    def register_startup_hook(
        self, fn: Callable[[], Any]
    ) -> None: ...

    @abstractmethod
    def register_shutdown_hook(
        self, fn: Callable[[], Any]
    ) -> None: ...

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
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_engine/unit/test_http_adapter_base.py -v
```
Expected: `6 passed`

**Step 5: Commit**

```bash
git add nest/engine/http_adapter.py \
        tests/test_engine/unit/test_http_adapter_base.py
git commit -m "feat(engine): add AbstractHttpAdapter — NestJS-inspired engine contract"
```

---

## Task 6: `nest/engine/__init__.py` — public exports

**Files:**
- Modify: `nest/engine/__init__.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_engine/unit/test_types.py (append to existing file)

def test_engine_package_exports():
    import nest.engine as engine
    assert hasattr(engine, "AbstractHttpAdapter")
    assert hasattr(engine, "RouteSpec")
    assert hasattr(engine, "ParamSpec")
    assert hasattr(engine, "HttpMethod")
    assert hasattr(engine, "Endpoint")
    assert hasattr(engine, "ExecutionContext")
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_engine/unit/test_types.py::test_engine_package_exports -v
```
Expected: `FAIL — AttributeError: module 'nest.engine' has no attribute 'AbstractHttpAdapter'`

**Step 3: Implement**

```python
# nest/engine/__init__.py
from nest.engine.execution_context import ExecutionContext, HttpExecutionContext
from nest.engine.http_adapter import AbstractHttpAdapter
from nest.engine.params import ParamSpec, VALID_SOURCES
from nest.engine.route_spec import RouteSpec
from nest.engine.types import Endpoint, HttpMethod

__all__ = [
    "AbstractHttpAdapter",
    "ExecutionContext",
    "Endpoint",
    "HttpExecutionContext",
    "HttpMethod",
    "ParamSpec",
    "RouteSpec",
    "VALID_SOURCES",
]
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_engine/unit/test_types.py -v
```
Expected: `3 passed` (existing 2 + new 1)

**Step 5: Commit**

```bash
git add nest/engine/__init__.py tests/test_engine/unit/test_types.py
git commit -m "feat(engine): expose public exports from nest.engine package"
```

---

## Task 7: `nest/http/__init__.py` — user-facing import facade

**Files:**
- Create: `nest/http/__init__.py`
- Create: `tests/test_engine/unit/test_http_facade.py`

**Goal:** Under the FastAPI default, `from nest.http import Request, Response, Depends` gives users the exact same `fastapi.Request`, `fastapi.Response`, `fastapi.Depends` objects. When a second engine lands, this file gets a runtime resolver. For now, it's a static re-export.

**Step 1: Write the failing test**

```python
# tests/test_engine/unit/test_http_facade.py
from __future__ import annotations


def test_request_is_fastapi_request():
    from nest.http import Request
    from fastapi import Request as FastAPIRequest
    assert Request is FastAPIRequest


def test_response_is_fastapi_response():
    from nest.http import Response
    from fastapi import Response as FastAPIResponse
    assert Response is FastAPIResponse


def test_depends_is_fastapi_depends():
    from nest.http import Depends
    from fastapi import Depends as FastAPIDepends
    assert Depends is FastAPIDepends


def test_http_exception_is_fastapi_http_exception():
    from nest.http import HTTPException
    from fastapi import HTTPException as FastAPIHTTPException
    assert HTTPException is FastAPIHTTPException
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_engine/unit/test_http_facade.py -v
```
Expected: `ModuleNotFoundError: No module named 'nest.http'`

**Step 3: Implement**

```python
# nest/http/__init__.py
"""
User-facing HTTP import facade.

Under the default FastAPI engine these are direct re-exports of the
corresponding fastapi symbols. When a second engine adapter is introduced,
this module will resolve based on the active adapter instead.

Recommended usage:
    from nest.http import Request, Response, Depends

FastAPI imports still work and are not deprecated in 0.7.x.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi import Request, Response

__all__ = ["Depends", "HTTPException", "Request", "Response"]
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_engine/unit/test_http_facade.py -v
```
Expected: `4 passed`

**Step 5: Commit**

```bash
git add nest/http/__init__.py tests/test_engine/unit/test_http_facade.py
git commit -m "feat(http): add nest/http facade — Request/Response/Depends aliases for FastAPI default"
```

---

## Task 8: Conformance test scaffold

**Files:**
- Create: `tests/test_engine/conformance/__init__.py`
- Create: `tests/test_engine/conformance/conftest.py`

**Goal:** Set up the parametrized `adapter` fixture so the conformance suite (added in PR 2) has a home. In PR 1 the fixture is wired but no conformance tests exist yet — that's fine.

**Step 1: Create the files (no test to fail first — this is pure scaffold)**

```python
# tests/test_engine/conformance/__init__.py
```

```python
# tests/test_engine/conformance/conftest.py
"""
Adapter conformance fixture.

Add new adapters to REGISTERED_ADAPTERS when they land.
Every test in tests/test_engine/conformance/ runs against each adapter.
"""
from __future__ import annotations

import pytest


def _fastapi_adapter():
    # Imported lazily — FastAPIAdapter doesn't exist until PR 2.
    from nest.engines.fastapi import FastAPIAdapter
    return FastAPIAdapter()


REGISTERED_ADAPTERS = [
    # pytest.param(_fastapi_adapter, id="fastapi"),   # uncomment when PR 2 lands
    # pytest.param(_litestar_adapter, id="litestar"), # phase 2
]


@pytest.fixture(params=REGISTERED_ADAPTERS)
def adapter(request):
    return request.param()
```

**Step 2: Verify the scaffold doesn't break the suite**

```bash
uv run pytest tests/ -v --tb=short 2>&1 | tail -20
```
Expected: all existing tests pass, conformance directory collected with 0 items (no tests yet).

**Step 3: Commit**

```bash
git add tests/test_engine/conformance/__init__.py \
        tests/test_engine/conformance/conftest.py
git commit -m "test(engine): scaffold conformance test directory for adapter-parametrized suite"
```

---

## Task 9: Full suite regression check

**Goal:** Verify the existing 34-file test suite still passes byte-identically with everything we just added.

**Step 1: Run full suite**

```bash
uv run pytest tests/ -v 2>&1 | tail -30
```
Expected: all original tests pass. The new test files (in `tests/test_engine/`) also pass. No test in `tests/test_core/`, `tests/test_common/`, `tests/test_websockets/` changed behavior.

**Step 2: Verify no fastapi imports leaked into nest/engine/**

```bash
grep -rE "^(from fastapi|import fastapi)" nest/engine/ nest/engine/**/*.py 2>/dev/null && echo "FAIL: fastapi leaked into nest/engine" || echo "OK: no fastapi in nest/engine"
```
Expected: `OK: no fastapi in nest/engine`

**Step 3: Verify nest/http/ imports cleanly**

```bash
python3 -c "import nest.http; print('OK')"
```
Expected: `OK`

**Step 4: Final commit (clean up if anything staged)**

```bash
git status
```
If clean: done. If anything unstaged: review and commit with a fix message.

---

## PR checklist before opening

- [ ] `uv run pytest tests/ -v` — all green
- [ ] `grep -rE "^(from fastapi|import fastapi)" nest/engine/` — empty (no output)
- [ ] `nest/engine/__init__.py` exports verified
- [ ] `nest/http/__init__.py` exports verified
- [ ] Conformance scaffold in place (PR 2 can immediately uncomment `fastapi` line)
- [ ] All new files have `from __future__ import annotations` at top
- [ ] No changes to any file under `nest/core/`, `nest/common/`, `nest/websockets/`, `tests/test_core/`, `tests/test_common/`, `tests/test_websockets/`
