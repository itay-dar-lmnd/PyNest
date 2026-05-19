from __future__ import annotations

from typing import Any, Callable

# Re-export HTTPMethod from its existing home to avoid duplication.
from nest.core.decorators.http_method import HTTPMethod as HttpMethod

Endpoint = Callable[..., Any]

__all__ = ["HttpMethod", "Endpoint"]
