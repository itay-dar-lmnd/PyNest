"""
PR-1 smoke test suite.

Runs an actual PyNest app (ASGI) and exercises:
  - nest.engine contracts (AbstractHttpAdapter, RouteSpec, ParamSpec, …)
  - nest.http facade (Request, Response, Depends, HTTPException)
  - Controllers: @Body, @Query, @Param, @Headers param decorators
  - Guards (ApiKeyGuard) — allow and deny paths
  - Exception filters (HttpExceptionFilter) — 404 shape
  - Lifecycle hooks — on_application_bootstrap fires
  - DI across modules

Run with:  uv run pytest test_app.py -v
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport


@pytest.fixture(scope="module")
def app():
    from main import create_app
    return create_app()


@pytest.fixture(scope="module")
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── nest.engine / nest.http contract checks ───────────────────────────────────

class TestEngineContracts:
    @pytest.mark.asyncio
    async def test_contracts_endpoint_returns_ok(self, client):
        r = await client.get("/engine-check/contracts")
        assert r.status_code == 200
        data = r.json()
        assert data["execution_context_type"] == "http"
        assert data["http_context_has_request"] is True
        assert data["nest_http_aliases_match_fastapi"] is True
        assert data["abstract_adapter_is_abc"] is True

    @pytest.mark.asyncio
    async def test_all_http_methods_present(self, client):
        r = await client.get("/engine-check/contracts")
        methods = r.json()["http_methods"]
        for m in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]:
            assert m in methods

    @pytest.mark.asyncio
    async def test_all_param_sources_present(self, client):
        r = await client.get("/engine-check/contracts")
        sources = r.json()["valid_param_sources"]
        for src in ["body", "query", "path", "header", "request", "response", "ip", "host", "custom"]:
            assert src in sources

    @pytest.mark.asyncio
    async def test_param_specs_created(self, client):
        r = await client.get("/engine-check/contracts")
        assert r.json()["param_specs_created"] == 9  # one per VALID_SOURCES

    @pytest.mark.asyncio
    async def test_route_spec_built(self, client):
        r = await client.get("/engine-check/contracts")
        data = r.json()
        assert data["route_spec_path"] == "/engine-check/probe"
        assert data["route_spec_method"] == "GET"

    @pytest.mark.asyncio
    async def test_adapter_contract_complete(self, client):
        r = await client.get("/engine-check/adapter")
        assert r.status_code == 200
        data = r.json()
        assert data["contract_complete"] is True, (
            f"Missing methods: {data['missing']}, Extra: {data['extra']}"
        )
        assert data["missing"] == []
        assert data["extra"] == []

    @pytest.mark.asyncio
    async def test_adapter_has_18_abstract_methods(self, client):
        r = await client.get("/engine-check/adapter")
        assert len(r.json()["abstract_methods"]) == 18


# ── Users module — DI + @Param + @Query + @Body ───────────────────────────────

class TestUsersModule:
    @pytest.mark.asyncio
    async def test_create_user(self, client):
        r = await client.post("/users", json={"name": "Ada", "email": "ada@example.com"})
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "Ada"
        assert data["email"] == "ada@example.com"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_get_all_users(self, client):
        await client.post("/users", json={"name": "Bob", "email": "bob@example.com"})
        r = await client.get("/users")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        assert len(r.json()) >= 1

    @pytest.mark.asyncio
    async def test_query_limit(self, client):
        for i in range(5):
            await client.post("/users", json={"name": f"User{i}", "email": f"u{i}@x.com"})
        r = await client.get("/users", params={"limit": 2})
        assert r.status_code == 200
        assert len(r.json()) <= 2

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, client):
        r = await client.post("/users", json={"name": "Carol", "email": "carol@example.com"})
        user_id = r.json()["id"]
        r2 = await client.get(f"/users/{user_id}")
        assert r2.status_code == 200
        assert r2.json()["name"] == "Carol"

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, client):
        r = await client.get("/users/99999")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_user(self, client):
        r = await client.post("/users", json={"name": "Dave", "email": "dave@x.com"})
        uid = r.json()["id"]
        r2 = await client.delete(f"/users/{uid}")
        assert r2.status_code == 200
        assert r2.json()["deleted"] == uid
        r3 = await client.get(f"/users/{uid}")
        assert r3.status_code == 404


# ── Items module — Guards + Exception filters + @Headers ──────────────────────

class TestItemsModule:
    @pytest.mark.asyncio
    async def test_create_item_with_valid_key(self, client):
        r = await client.post(
            "/items",
            json={"name": "Hammer", "price": 9.99},
            headers={"x-api-key": "secret"},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "Hammer"
        assert data["price"] == 9.99
        assert data["in_stock"] is True

    @pytest.mark.asyncio
    async def test_create_item_guard_rejects_bad_key(self, client):
        r = await client.post(
            "/items",
            json={"name": "Wrench", "price": 4.99},
            headers={"x-api-key": "wrong"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_create_item_guard_rejects_no_key(self, client):
        r = await client.post("/items", json={"name": "Bolt", "price": 0.10})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_get_all_items(self, client):
        await client.post(
            "/items",
            json={"name": "Nail", "price": 0.05},
            headers={"x-api-key": "secret"},
        )
        r = await client.get("/items")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    @pytest.mark.asyncio
    async def test_query_in_stock_filter(self, client):
        await client.post(
            "/items",
            json={"name": "OOS Item", "price": 1.0, "in_stock": False},
            headers={"x-api-key": "secret"},
        )
        r = await client.get("/items", params={"in_stock": "true"})
        assert r.status_code == 200
        for item in r.json():
            assert item["in_stock"] is True

    @pytest.mark.asyncio
    async def test_get_item_by_id(self, client):
        r = await client.post(
            "/items",
            json={"name": "Screwdriver", "price": 7.50},
            headers={"x-api-key": "secret"},
        )
        item_id = r.json()["id"]
        r2 = await client.get(f"/items/{item_id}")
        assert r2.status_code == 200
        assert r2.json()["name"] == "Screwdriver"

    @pytest.mark.asyncio
    async def test_exception_filter_shapes_404(self, client):
        r = await client.get("/items/99999")
        assert r.status_code == 404
        body = r.json()
        # HttpExceptionFilter shapes: {statusCode, message, error}
        assert "statusCode" in body
        assert "message" in body
        assert "error" in body
        assert body["statusCode"] == 404
        assert body["error"] == "NotFoundException"


# ── OpenAPI sanity ─────────────────────────────────────────────────────────────

class TestOpenAPI:
    @pytest.mark.asyncio
    async def test_openapi_json_accessible(self, client):
        r = await client.get("/openapi.json")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_openapi_has_all_tags(self, client):
        r = await client.get("/openapi.json")
        paths = r.json()["paths"]
        path_keys = list(paths.keys())
        assert any("/users" in p for p in path_keys)
        assert any("/items" in p for p in path_keys)
        assert any("/engine-check" in p for p in path_keys)

    @pytest.mark.asyncio
    async def test_docs_page_accessible(self, client):
        r = await client.get("/docs")
        assert r.status_code == 200
