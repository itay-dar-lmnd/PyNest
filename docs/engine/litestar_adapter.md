# Litestar Adapter

The first non-FastAPI engine PyNest supports. Wraps a Litestar application and
exposes the same `AbstractHttpAdapter` contract.

## Installation

Litestar is an optional install. Install the extra:

```bash
pip install "pynest-api[litestar]"
# or with uv:
uv add "pynest-api[litestar]"
```

This installs `litestar[standard]>=2.13` alongside PyNest core.

## Usage

### Switch engine at construction time

```python
from nest.core import PyNestFactory
from nest.engines.litestar import LitestarAdapter

app = PyNestFactory.create(
    AppModule,
    adapter=LitestarAdapter(),
)
```

That's it. Same `AppModule`, same controllers, same modules — different engine.

### With Litestar kwargs

```python
from nest.engines.litestar import LitestarAdapter

app = PyNestFactory.create(
    AppModule,
    adapter=LitestarAdapter(
        title="My API",
        version="1.0.0",
        debug=True,
    ),
)
```

### Bring your own Litestar instance

```python
from litestar import Litestar
from nest.engines.litestar import LitestarAdapter

existing = Litestar(route_handlers=[my_legacy_handler])
app = PyNestFactory.create(
    AppModule,
    adapter=LitestarAdapter(instance=existing),
)
```

PyNest registers its controllers alongside the existing Litestar routes.

### Switching engines via environment variable

A common pattern — read an env var at boot:

```python
import os
from nest.core import PyNestFactory


def build_adapter():
    if os.environ.get("PYNEST_ENGINE") == "litestar":
        from nest.engines.litestar import LitestarAdapter
        return LitestarAdapter(title="My API")
    from nest.engines.fastapi import FastAPIAdapter
    return FastAPIAdapter(title="My API")


app = PyNestFactory.create(AppModule, adapter=build_adapter())
```

Then choose your engine without code changes:

```bash
PYNEST_ENGINE=fastapi  uvicorn main:app    # default
PYNEST_ENGINE=litestar uvicorn main:app
```

The PyNest test-app does exactly this and runs the same 77 tests against both
engines.

## What works

Every PyNest feature works on the Litestar adapter:

| Feature                                | Status |
|----------------------------------------|--------|
| Controllers + all HTTP methods         | ✅     |
| `@Body` / `@Query` / `@Param` / `@Headers` | ✅ |
| `@Req` / `@Res` / `@Ip` / `@HostParam` | ✅     |
| `createParamDecorator` (custom decorators) | ✅ |
| Pipes (transform / validate chains)    | ✅     |
| Guards (`BaseGuard`, `@UseGuards`, multi-guard) | ✅ |
| Exception filters (`@Catch`, `@UseFilters`, `app.use_global_filters`) | ✅ |
| Lifecycle hooks (`OnApplicationBootstrap`, `OnApplicationShutdown`) | ✅ |
| WebSocket gateways (`@WebSocketGateway`, `@SubscribeMessage`) | ✅ |
| Dependency injection across modules    | ✅     |
| Module imports / exports               | ✅     |
| Nested Pydantic DTOs                   | ✅     |
| Database integration (any provider)    | ✅     |
| OpenAPI generation                     | ✅ (native Litestar OpenAPI) |
| Middleware (`app.use`)                 | ✅     |
| CORS (`adapter.enable_cors`)           | ✅     |

## Litestar quirks vs FastAPI

The adapter papers over the differences. Specific quirks worth knowing:

### 1. Default HTTP status codes

Litestar defaults `POST` to 201 and `DELETE` to 204. FastAPI defaults both to 200.
The adapter overrides Litestar's defaults when the route doesn't specify a
`status_code`, so PyNest controllers behave identically:

```python
@Post("/")   # Returns 200 by default on both engines
def create(self, body: Dto = Body()): ...

@Post("/")
@HttpCode(201)   # Explicit — 201 on both engines
def create(self, body: Dto = Body()): ...
```

### 2. Path parameter typing

FastAPI infers path-param types from the handler signature: `/{id}` + `id: int`.
Litestar requires the type in the path: `/{id:int}`. The adapter rewrites paths
automatically based on `RouteSpec.params`:

```python
# Your code (engine-neutral):
@Get("/{item_id}")
def show(self, item_id: int = Param("item_id")): ...

# What the adapter registers on Litestar:
# "/{item_id:int}"
```

### 3. Body parameter naming

Litestar reserves the parameter name `body` for raw bytes. If your handler is
`def create(self, body: Dto = Body())`, the adapter renames it to `data` in the
Litestar registration but forwards the resolved value back to your endpoint as
`body=`. Transparent to user code.

### 4. WebSocket parameter naming

Litestar requires the WebSocket handler's parameter to be named `socket` and
the handler to have `-> None`. PyNest's `@WebSocketGateway` machinery already
uses `socket` and returns `None`, so this is automatic.

### 5. Exception handlers must be sync

Litestar calls exception handlers synchronously without awaiting. Write your
filters with `def catch(...)` rather than `async def catch(...)` for
cross-engine compatibility:

```python
@Catch(HttpException)
class HttpExceptionFilter(ExceptionFilter):
    def catch(self, exception, host):    # sync — portable
        return JSONResponse(...)
```

Async filters work on FastAPI; sync filters work on both.

### 6. Exception filter response objects

Filters often return Starlette `JSONResponse` (FastAPI's default). The Litestar
adapter automatically converts these to Litestar's native `Response` so the
same filter works on both engines without changes.

### 7. Missing-required-param status code

| Engine   | Missing required query param | Validation error |
|----------|------------------------------|------------------|
| FastAPI  | 422                          | 422              |
| Litestar | 400                          | 400              |

Both are valid 4xx codes. If you assert on exact status, branch on engine.

### 8. OpenAPI paths

| Engine   | JSON schema path        | UI path |
|----------|-------------------------|---------|
| FastAPI  | `/openapi.json`         | `/docs` |
| Litestar | `/docs/openapi.json`    | `/docs` |

The `/docs` UI works on both. If you fetch the JSON schema programmatically,
try both paths or detect the engine.

### 9. `nest.http.Request` and `nest.http.Response`

Under the FastAPI engine, `nest.http.Request` is `fastapi.Request`. Under
Litestar, it's `litestar.Request`. Cross-engine code should:

- Use `nest.http.Request` in type annotations (resolves per engine)
- Avoid engine-specific Request methods
- Use `adapter.get_request_method(req)`, `adapter.get_request_headers(req)`,
  etc. for portable request access

## How the adapter works internally

`nest/engines/litestar/adapter.py` implements all 18 abstract methods. The
heavy lifting is in `add_route(spec)`:

1. **Path rewrite** — `/items/{id}` becomes `/items/{id:int}` based on `RouteSpec.params`
2. **Param binding** (`bind_params`) — translates `ParamSpec` defaults into Litestar's `Parameter()` / `Body()` markers, or `Provide()` dependencies when pipes are involved
3. **Filter wrapping** — exceptions route through PyNest's `ExceptionFilter.catch`; Starlette responses convert to Litestar responses
4. **Guard translation** — PyNest `BaseGuard` becomes a Litestar guard `(connection, handler) → None` raising `PermissionDeniedException` on denial
5. **Native registration** — uses Litestar's `@get(...)` / `@post(...)` decorator functions called programmatically, then `app.register(handler)`

The `nest/engines/litestar/params.py` module is the translation layer:

| `ParamSpec.source` | Litestar primitive                       |
|--------------------|------------------------------------------|
| `body`             | `Body()` annotation default; param renamed to `data` |
| `query`            | `Parameter(query=name)`                  |
| `header`           | `Parameter(header=name)`                 |
| `path`             | (read from path natively via `{name:type}`) |
| `request`          | parameter annotated as `litestar.Request`|
| `response`         | `Provide()` that builds a Response       |
| `ip`               | `Provide()` reading `request.client.host`|
| `host`             | `Provide()` reading `request.url.hostname` |
| `custom`           | `Provide()` wrapping the user-supplied factory |
| any source + pipes | `Provide()` that extracts + applies pipes + coerces |

## Conformance & test coverage

The Litestar adapter passes the full PyNest conformance suite
(`tests/test_engine/conformance/`) — 17 tests covering route registration,
param binding, request accessors, middleware, exception handlers, lifespan,
CORS, and WebSockets. The same 17 tests pass against the FastAPI adapter.

Plus the test-app (`test-app/`) runs its full 77-test suite against both
engines — including SQLite database integration, multi-guard auth flows,
WebSocket chat, and concurrent stress tests.

## Known limitations

1. **`security_scheme` on guards** — FastAPI-specific. Litestar guards extract
   credentials by best-effort header parsing for common scheme types
   (`APIKeyHeader`, `HTTPBearer`, `OAuth2PasswordBearer`). Custom scheme types
   may not extract credentials correctly under Litestar.

2. **Sync controllers** — Litestar warns about synchronous controller methods
   that aren't marked `sync_to_thread`. Suppress via
   `LITESTAR_WARN_IMPLICIT_SYNC_TO_THREAD=0` or convert your methods to async.

3. **OpenAPI shape** — Litestar's OpenAPI schema is structured differently
   from FastAPI's. If your code consumes the JSON schema programmatically,
   test on both engines.

## See also

- [Engine Overview](overview.md)
- [FastAPI Adapter](fastapi_adapter.md)
- [Writing an Adapter](writing_an_adapter.md)
- [Migration to 0.7](migration_0.7.md)
