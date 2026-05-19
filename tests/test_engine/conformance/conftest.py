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
