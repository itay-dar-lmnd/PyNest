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
    assert Endpoint is not None
