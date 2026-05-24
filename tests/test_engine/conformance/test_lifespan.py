"""Conformance tests: startup/shutdown lifecycle hooks."""
from __future__ import annotations

from starlette.testclient import TestClient

from nest.engine.route_spec import RouteSpec
from nest.engine.types import HttpMethod


def test_startup_and_shutdown_hooks_fire(adapter):
    events: list[str] = []

    async def on_startup():
        events.append("startup")

    async def on_shutdown():
        events.append("shutdown")

    adapter.register_startup_hook(on_startup)
    adapter.register_shutdown_hook(on_shutdown)

    async def handler() -> dict:
        events.append("request")
        return {"ok": True}

    adapter.add_route(RouteSpec(method=HttpMethod.GET, path="/l", endpoint=handler))

    # TestClient runs lifespan automatically via context manager — works for
    # both FastAPI and Litestar (both implement ASGI lifespan).
    with TestClient(adapter.get_http_server()) as c:
        c.get("/l")

    assert events == ["startup", "request", "shutdown"]


def test_sync_startup_hook(adapter):
    fired = []

    def on_startup_sync():
        fired.append(True)

    adapter.register_startup_hook(on_startup_sync)

    async def handler() -> dict:
        return {}

    adapter.add_route(RouteSpec(method=HttpMethod.GET, path="/s", endpoint=handler))
    with TestClient(adapter.get_http_server()) as c:
        c.get("/s")
    assert fired == [True]
