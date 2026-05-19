"""
PR-1 smoke + edge-case + stress test suite.

Run: uv run pytest test_app.py -v --asyncio-mode=auto

Covers:
  [engine]    nest.engine contracts (7 tests)
  [users]     basic CRUD + param decorators + DI (6 tests)
  [items]     guards + exception filters + @Headers (7 tests)
  [catalog]   nested Pydantic models, cross-module exports, stock logic (8 tests)
  [pipeline]  custom param decorators, pipes, async endpoints, Req/Ip (14 tests)
  [auth]      cross-module DI, multi-guard, token management (8 tests)
  [openapi]   schema generation (3 tests)
  [compat]    from __future__ import annotations compatibility (3 tests)
  [stress]    concurrent requests, large payloads, rapid fire (5 tests)
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from httpx import AsyncClient, ASGITransport


# ── fixtures ──────────────────────────────────────────────────────────────────

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


# ═══════════════════════════════════════════════════════════════════════════════
# ENGINE CONTRACTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestEngineContracts:
    async def test_contracts_all_symbols_present(self, client):
        r = await client.get("/engine-check/contracts")
        assert r.status_code == 200
        d = r.json()
        assert d["execution_context_type"] == "http"
        assert d["http_context_has_request"] is True
        assert d["nest_http_aliases_match_fastapi"] is True
        assert d["abstract_adapter_is_abc"] is True

    async def test_all_http_methods_present(self, client):
        r = await client.get("/engine-check/contracts")
        for m in ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]:
            assert m in r.json()["http_methods"]

    async def test_all_9_param_sources_present(self, client):
        r = await client.get("/engine-check/contracts")
        sources = r.json()["valid_param_sources"]
        for src in ["body","query","path","header","request","response","ip","host","custom"]:
            assert src in sources

    async def test_param_specs_created_for_all_sources(self, client):
        r = await client.get("/engine-check/contracts")
        assert r.json()["param_specs_created"] == 9

    async def test_route_spec_built(self, client):
        r = await client.get("/engine-check/contracts")
        assert r.json()["route_spec_path"] == "/engine-check/probe"
        assert r.json()["route_spec_method"] == "GET"

    async def test_adapter_contract_complete(self, client):
        r = await client.get("/engine-check/adapter")
        d = r.json()
        assert d["contract_complete"] is True, f"Missing: {d['missing']}, Extra: {d['extra']}"

    async def test_adapter_has_exactly_18_abstract_methods(self, client):
        r = await client.get("/engine-check/adapter")
        assert len(r.json()["abstract_methods"]) == 18


# ═══════════════════════════════════════════════════════════════════════════════
# USERS MODULE  — basic CRUD + @Body @Query @Param
# ═══════════════════════════════════════════════════════════════════════════════

class TestUsersModule:
    async def test_create_user(self, client):
        r = await client.post("/users", json={"name": "Ada", "email": "ada@example.com"})
        assert r.status_code == 201
        assert r.json()["name"] == "Ada"

    async def test_get_all_returns_list(self, client):
        await client.post("/users", json={"name": "Bob", "email": "bob@example.com"})
        r = await client.get("/users")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_query_limit(self, client):
        for i in range(5):
            await client.post("/users", json={"name": f"User{i}", "email": f"u{i}@x.com"})
        r = await client.get("/users", params={"limit": 2})
        assert len(r.json()) <= 2

    async def test_get_user_by_id(self, client):
        r = await client.post("/users", json={"name": "Carol", "email": "carol@x.com"})
        uid = r.json()["id"]
        r2 = await client.get(f"/users/{uid}")
        assert r2.json()["name"] == "Carol"

    async def test_get_nonexistent_user_returns_404(self, client):
        r = await client.get("/users/99999")
        assert r.status_code == 404

    async def test_delete_user(self, client):
        r = await client.post("/users", json={"name": "Dave", "email": "d@x.com"})
        uid = r.json()["id"]
        assert (await client.delete(f"/users/{uid}")).status_code == 200
        assert (await client.get(f"/users/{uid}")).status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# ITEMS MODULE  — guards + filters + @Headers
# ═══════════════════════════════════════════════════════════════════════════════

class TestItemsModule:
    async def test_create_with_valid_key(self, client):
        r = await client.post("/items", json={"name": "Hammer", "price": 9.99},
                              headers={"x-api-key": "secret"})
        assert r.status_code == 201
        assert r.json()["name"] == "Hammer"

    async def test_guard_rejects_bad_key(self, client):
        r = await client.post("/items", json={"name": "Wrench", "price": 4.99},
                              headers={"x-api-key": "wrong"})
        assert r.status_code == 403

    async def test_guard_rejects_no_key(self, client):
        assert (await client.post("/items", json={"name": "Bolt", "price": 0.1})).status_code == 403

    async def test_get_all_items(self, client):
        await client.post("/items", json={"name": "Nail", "price": 0.05},
                          headers={"x-api-key": "secret"})
        assert (await client.get("/items")).status_code == 200

    async def test_in_stock_filter(self, client):
        await client.post("/items", json={"name": "OOS", "price": 1.0, "in_stock": False},
                          headers={"x-api-key": "secret"})
        r = await client.get("/items", params={"in_stock": "true"})
        assert all(i["in_stock"] for i in r.json())

    async def test_exception_filter_shapes_not_found(self, client):
        r = await client.get("/items/99999")
        assert r.status_code == 404
        assert r.json() == {"statusCode": 404, "message": "Item 99999 not found",
                            "error": "NotFoundException"}

    async def test_get_item_by_id(self, client):
        r = await client.post("/items", json={"name": "Screwdriver", "price": 7.5},
                              headers={"x-api-key": "secret"})
        iid = r.json()["id"]
        assert (await client.get(f"/items/{iid}")).json()["name"] == "Screwdriver"


# ═══════════════════════════════════════════════════════════════════════════════
# CATALOG MODULE  — nested Pydantic, cross-module export, PUT stock
# ═══════════════════════════════════════════════════════════════════════════════

class TestCatalogModule:
    def _product_payload(self, name="Laptop", stock=5):
        return {
            "name": name,
            "description": f"A great {name}",
            "variants": [
                {"sku": f"{name[:3].upper()}-001", "price": 999.0, "stock": stock,
                 "attributes": {"color": "silver", "ram": "16GB"}},
                {"sku": f"{name[:3].upper()}-002", "price": 1199.0, "stock": stock + 2,
                 "attributes": {"color": "space-gray", "ram": "32GB"}},
            ],
            "dimensions": {"width": 30.0, "height": 20.0, "depth": 1.5},
            "tags": [{"name": "electronics", "color": "blue"},
                     {"name": "laptop", "color": "green"}],
        }

    async def test_create_product_nested_model(self, client):
        r = await client.post("/catalog", json=self._product_payload())
        assert r.status_code == 201
        d = r.json()
        assert d["name"] == "Laptop"
        assert d["total_stock"] == 12
        assert len(d["variants"]) == 2
        assert d["dimensions"]["depth"] == 1.5
        assert len(d["tags"]) == 2

    async def test_create_product_duplicate_sku_rejected(self, client):
        payload = {
            "name": "BadProd",
            "variants": [
                {"sku": "DUP-001", "price": 1.0, "stock": 1},
                {"sku": "DUP-001", "price": 2.0, "stock": 1},  # duplicate
            ],
        }
        r = await client.post("/catalog", json=payload)
        assert r.status_code == 409

    async def test_list_by_tag(self, client):
        await client.post("/catalog", json=self._product_payload("Phone"))
        r = await client.get("/catalog", params={"tag": "electronics"})
        assert r.status_code == 200
        assert all("electronics" in [t["name"] for t in p["tags"]] for p in r.json())

    async def test_list_min_stock_filter(self, client):
        await client.post("/catalog", json=self._product_payload("Tablet", stock=0))
        r = await client.get("/catalog", params={"min_stock": 1})
        assert all(p["total_stock"] >= 1 for p in r.json())

    async def test_get_product_by_id(self, client):
        r = await client.post("/catalog", json=self._product_payload("Monitor"))
        pid = r.json()["id"]
        r2 = await client.get(f"/catalog/{pid}")
        assert r2.status_code == 200
        assert r2.json()["name"] == "Monitor"

    async def test_get_product_not_found(self, client):
        assert (await client.get("/catalog/99999")).status_code == 404

    async def test_update_stock_add(self, client):
        r = await client.post("/catalog", json=self._product_payload("Keyboard", stock=3))
        pid = r.json()["id"]
        sku = r.json()["variants"][0]["sku"]
        r2 = await client.put(f"/catalog/{pid}/stock",
                               json={"sku": sku, "delta": 10})
        assert r2.status_code == 200
        variant = next(v for v in r2.json()["variants"] if v["sku"] == sku)
        assert variant["stock"] == 13

    async def test_update_stock_below_zero_rejected(self, client):
        r = await client.post("/catalog", json=self._product_payload("Mouse", stock=2))
        pid = r.json()["id"]
        sku = r.json()["variants"][0]["sku"]
        r2 = await client.put(f"/catalog/{pid}/stock",
                               json={"sku": sku, "delta": -100})
        assert r2.status_code == 409


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE MODULE  — pipes, custom param decorators, async, Req/Ip
# ═══════════════════════════════════════════════════════════════════════════════

class TestPipelineModule:
    async def test_trim_and_upper_pipe(self, client):
        r = await client.get("/pipeline/trim", params={"text": "  hello world  "})
        assert r.status_code == 200
        assert r.json()["result"] == "HELLO WORLD"

    async def test_clamp_pipe_within_range(self, client):
        r = await client.get("/pipeline/clamp/50")
        assert r.json()["result"] == 50

    async def test_clamp_pipe_clamps_low(self, client):
        r = await client.get("/pipeline/clamp/0")
        assert r.json()["result"] == 1

    async def test_clamp_pipe_clamps_high(self, client):
        r = await client.get("/pipeline/clamp/9999")
        assert r.json()["result"] == 100

    async def test_positive_int_pipe_valid(self, client):
        r = await client.get("/pipeline/positive", params={"n": "7"})
        assert r.json()["result"] == 7

    async def test_positive_int_pipe_rejects_zero(self, client):
        r = await client.get("/pipeline/positive", params={"n": "0"})
        assert r.status_code == 422
        assert "positive" in r.json().get("detail", "").lower()

    async def test_custom_request_id_decorator(self, client):
        r = await client.get("/pipeline/request-id",
                             headers={"x-request-id": "req-abc-123"})
        assert r.json()["request_id"] == "req-abc-123"

    async def test_custom_request_id_missing_returns_unknown(self, client):
        r = await client.get("/pipeline/request-id")
        assert r.json()["request_id"] == "unknown"

    async def test_user_agent_decorator(self, client):
        r = await client.get("/pipeline/user-agent",
                             headers={"user-agent": "TestBot/1.0"})
        assert r.json()["user_agent"] == "TestBot/1.0"

    async def test_all_query_params_decorator(self, client):
        r = await client.get("/pipeline/query-dump",
                             params={"a": "1", "b": "2", "c": "3"})
        assert r.json()["all_params"] == {"a": "1", "b": "2", "c": "3"}

    async def test_async_compute_endpoint(self, client):
        r = await client.get("/pipeline/compute/9")
        assert r.status_code == 200
        assert r.json() == {"input": 9, "result": 81, "async": True}

    async def test_async_batch_endpoint(self, client):
        r = await client.post("/pipeline/batch", json=[1, 2, 3, 4, 5])
        assert r.status_code == 201
        d = r.json()
        assert d["count"] == 5
        assert d["results"][2] == {"input": 3, "result": 9, "async": True}

    async def test_req_injection(self, client):
        r = await client.get("/pipeline/method")
        assert r.json()["method"] == "GET"

    async def test_ip_injection(self, client):
        r = await client.get("/pipeline/ip")
        assert "ip" in r.json()


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH MODULE  — cross-module DI, multi-guard, token management
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuthModule:
    async def test_check_valid_token(self, client):
        r = await client.get("/auth/check",
                             headers={"authorization": "Bearer admin-token"})
        assert r.status_code == 200
        d = r.json()
        assert d["token_valid"] is True
        assert d["is_admin"] is True

    async def test_check_read_token(self, client):
        r = await client.get("/auth/check",
                             headers={"authorization": "Bearer read-token"})
        assert r.json()["is_admin"] is False

    async def test_check_invalid_token(self, client):
        r = await client.get("/auth/check",
                             headers={"authorization": "Bearer garbage"})
        assert r.json()["token_valid"] is False

    async def test_protected_with_valid_bearer(self, client):
        r = await client.get("/auth/protected",
                             headers={"authorization": "Bearer read-token"})
        assert r.status_code == 200
        assert r.json()["message"] == "Access granted"

    async def test_protected_rejects_invalid(self, client):
        r = await client.get("/auth/protected",
                             headers={"authorization": "Bearer bad"})
        assert r.status_code == 403

    async def test_admin_only_with_admin_token(self, client):
        r = await client.get("/auth/admin-only",
                             headers={"authorization": "Bearer admin-token"})
        assert r.status_code == 200

    async def test_admin_only_rejects_read_token(self, client):
        r = await client.get("/auth/admin-only",
                             headers={"authorization": "Bearer read-token"})
        assert r.status_code == 403

    async def test_add_token_requires_admin(self, client):
        # Non-admin cannot add tokens
        r = await client.post("/auth/tokens",
                               json={"token": "new-token"},
                               headers={"authorization": "Bearer read-token"})
        assert r.status_code == 403
        # Admin can add tokens
        r2 = await client.post("/auth/tokens",
                                json={"token": "extra-token"},
                                headers={"authorization": "Bearer admin-token"})
        assert r2.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# OPENAPI
# ═══════════════════════════════════════════════════════════════════════════════

class TestOpenAPI:
    async def test_openapi_json_accessible(self, client):
        assert (await client.get("/openapi.json")).status_code == 200

    async def test_openapi_has_all_modules(self, client):
        paths = list((await client.get("/openapi.json")).json()["paths"].keys())
        for prefix in ["/users", "/items", "/catalog", "/pipeline", "/auth", "/engine-check"]:
            assert any(p.startswith(prefix) for p in paths), f"Missing prefix: {prefix}"

    async def test_docs_page_accessible(self, client):
        assert (await client.get("/docs")).status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# FUTURE-ANNOTATIONS COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestFutureAnnotationsCompat:
    """
    Verifies that controllers using `from __future__ import annotations` work
    correctly after the get_type_hints() fix in nest/common/decorators.py.
    All controller files in this app use future annotations.
    """

    async def test_body_with_pydantic_model(self, client):
        """@Body() with a Pydantic model works despite future annotations."""
        r = await client.post("/users", json={"name": "FutureUser", "email": "f@x.com"})
        assert r.status_code == 201
        assert r.json()["name"] == "FutureUser"

    async def test_query_with_typed_annotation(self, client):
        """@Query() with int annotation resolves correctly."""
        r = await client.get("/users", params={"limit": "3"})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    async def test_nested_pydantic_body(self, client):
        """@Body() with deeply-nested Pydantic models works."""
        r = await client.post("/catalog", json={
            "name": "FutureProduct",
            "variants": [{"sku": "FP-001", "price": 1.0, "stock": 1}],
            "tags": [{"name": "test"}],
        })
        assert r.status_code == 201
        assert r.json()["name"] == "FutureProduct"


# ═══════════════════════════════════════════════════════════════════════════════
# STRESS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestStress:
    async def test_concurrent_reads(self, client):
        """50 concurrent GET requests — no errors, all return 200."""
        tasks = [client.get("/catalog") for _ in range(50)]
        responses = await asyncio.gather(*tasks)
        statuses = [r.status_code for r in responses]
        assert all(s == 200 for s in statuses), f"Got non-200: {set(statuses)}"

    async def test_concurrent_async_compute(self, client):
        """30 concurrent calls to the async compute endpoint."""
        tasks = [client.get(f"/pipeline/compute/{i+1}") for i in range(30)]
        responses = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in responses)
        results = {r.json()["input"]: r.json()["result"] for r in responses}
        for i in range(1, 31):
            assert results[i] == i * i

    async def test_rapid_fire_create_and_read(self, client):
        """100 interleaved writes + reads — verifies no race conditions in in-memory store."""
        creates = [
            client.post("/users", json={"name": f"Rapid{i}", "email": f"r{i}@x.com"})
            for i in range(50)
        ]
        reads = [client.get("/users") for _ in range(50)]
        all_tasks = creates + reads
        responses = await asyncio.gather(*all_tasks)
        errors = [r for r in responses if r.status_code >= 500]
        assert not errors, f"{len(errors)} server errors in rapid-fire test"

    async def test_large_payload(self, client):
        """POST a product with 200 variants — verifies no payload-size issues."""
        variants = [
            {"sku": f"SKU-{i:04d}", "price": float(i), "stock": i % 10,
             "attributes": {"size": str(i), "meta": "x" * 50}}
            for i in range(200)
        ]
        r = await client.post("/catalog", json={
            "name": "Mega Product",
            "variants": variants,
            "tags": [{"name": f"tag{i}"} for i in range(20)],
        })
        assert r.status_code == 201
        assert r.json()["total_stock"] == sum(i % 10 for i in range(200))
        assert len(r.json()["variants"]) == 200

    async def test_throughput_baseline(self, client):
        """200 sequential requests must complete in under 5 seconds."""
        start = time.monotonic()
        for _ in range(200):
            r = await client.get("/pipeline/request-id")
            assert r.status_code == 200
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"Throughput too slow: {elapsed:.2f}s for 200 requests"
