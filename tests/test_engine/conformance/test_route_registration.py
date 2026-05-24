"""Conformance tests: route registration via adapter.add_route()."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from nest.engine.params import ParamSpec
from nest.engine.route_spec import RouteSpec
from nest.engine.types import HttpMethod


@pytest.mark.asyncio
async def test_add_route_get_no_params(adapter):
    async def handler() -> dict:
        return {"hello": "world"}

    adapter.add_route(RouteSpec(method=HttpMethod.GET, path="/hello", endpoint=handler))
    async with AsyncClient(
        transport=ASGITransport(adapter.get_http_server()), base_url="http://t"
    ) as c:
        r = await c.get("/hello")
        assert r.status_code == 200
        assert r.json() == {"hello": "world"}


@pytest.mark.asyncio
async def test_add_route_with_path_param(adapter):
    async def handler(item_id: int = ParamSpec(source="path", name="item_id")) -> dict:
        return {"id": item_id}

    adapter.add_route(
        RouteSpec(
            method=HttpMethod.GET,
            path="/items/{item_id}",
            endpoint=handler,
            params=(ParamSpec(source="path", name="item_id", annotation=int),),
        )
    )
    async with AsyncClient(
        transport=ASGITransport(adapter.get_http_server()), base_url="http://t"
    ) as c:
        r = await c.get("/items/42")
        assert r.status_code == 200
        assert r.json() == {"id": 42}


@pytest.mark.asyncio
async def test_add_route_post_returns_201_with_status_code(adapter):
    async def handler() -> dict:
        return {"created": True}

    adapter.add_route(
        RouteSpec(
            method=HttpMethod.POST,
            path="/things",
            endpoint=handler,
            status_code=201,
        )
    )
    async with AsyncClient(
        transport=ASGITransport(adapter.get_http_server()), base_url="http://t"
    ) as c:
        r = await c.post("/things")
        assert r.status_code == 201


@pytest.mark.asyncio
async def test_add_route_tags_appear_in_openapi(adapter):
    async def handler() -> dict:
        return {}

    adapter.add_route(
        RouteSpec(
            method=HttpMethod.GET,
            path="/tagged",
            endpoint=handler,
            tags=("custom-tag",),
        )
    )
    # OpenAPI JSON lives at different paths per engine:
    #   FastAPI  → /openapi.json
    #   Litestar → /docs/openapi.json
    candidate_paths = ["/openapi.json", "/docs/openapi.json"]
    async with AsyncClient(
        transport=ASGITransport(adapter.get_http_server()), base_url="http://t"
    ) as c:
        spec = None
        for path in candidate_paths:
            r = await c.get(path)
            if r.status_code == 200 and "paths" in r.json():
                spec = r.json()
                break
        assert spec is not None, f"Couldn't find OpenAPI spec at any of {candidate_paths}"
        op = spec["paths"]["/tagged"]["get"]
        assert "custom-tag" in op.get("tags", [])


@pytest.mark.asyncio
async def test_add_route_all_http_methods(adapter):
    def make_handler(captured_method):
        async def handler() -> dict:
            return {"method": captured_method.value}
        return handler

    for method in [HttpMethod.GET, HttpMethod.POST, HttpMethod.PUT,
                   HttpMethod.PATCH, HttpMethod.DELETE]:
        # Litestar defaults DELETE to status 204 (no body allowed); force 200
        # so the conformance test can return a JSON body uniformly.
        adapter.add_route(
            RouteSpec(
                method=method,
                path=f"/m{method.value.lower()}",
                endpoint=make_handler(method),
                status_code=200,
            )
        )

    async with AsyncClient(
        transport=ASGITransport(adapter.get_http_server()), base_url="http://t"
    ) as c:
        assert (await c.get("/mget")).status_code == 200
        assert (await c.post("/mpost")).status_code == 200
        assert (await c.put("/mput")).status_code == 200
        assert (await c.patch("/mpatch")).status_code == 200
        assert (await c.delete("/mdelete")).status_code == 200
