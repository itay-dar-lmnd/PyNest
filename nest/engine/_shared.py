"""
Engine-neutral helpers shared across HTTP adapters (FastAPI, Litestar, Blacksheep).

These were previously duplicated verbatim in each engine's ``params.py`` /
``adapter.py``. Centralizing them keeps cross-engine behaviour identical and lets
a new adapter be a thin binding rather than yet another copy.

Nothing here imports a web framework — the only engine-specific seam is passed in
(``error_cls`` for pipe failures, ``convert`` for filter responses).
"""
from __future__ import annotations

import inspect
from typing import Any, Callable, Optional, Tuple

from pydantic import TypeAdapter

from nest.common.exceptions import ArgumentsHost
from nest.engine.params import ParamSpec


def has_param_specs(endpoint: Callable) -> bool:
    """True if any parameter of ``endpoint`` has a ParamSpec default."""
    signature = inspect.signature(endpoint)
    return any(
        isinstance(parameter.default, ParamSpec)
        for parameter in signature.parameters.values()
    )


def coerce_value(value: Any, annotation: Any) -> Any:
    """Validate/convert ``value`` to ``annotation`` via Pydantic (no-op when untyped)."""
    if value is None or annotation in {inspect.Parameter.empty, Any}:
        return value
    if inspect.isclass(annotation) and isinstance(value, annotation):
        return value
    return TypeAdapter(annotation).validate_python(value)


async def apply_pipes(value: Any, pipes: Tuple[Any, ...], error_cls: type) -> Any:
    """
    Apply pipes in order.

    A pipe may be a class (instantiated here), a plain callable, or an object
    exposing ``transform`` — sync or async. Validation errors are re-raised as
    ``error_cls(status_code=422, detail=...)`` so each engine renders its native
    422 response. ``error_cls`` is the only engine-specific seam.
    """
    for pipe in pipes:
        pipe_instance = pipe() if inspect.isclass(pipe) else pipe
        try:
            if hasattr(pipe_instance, "transform"):
                value = pipe_instance.transform(value)
            elif callable(pipe_instance):
                value = pipe_instance(value)
            else:
                raise TypeError("Pipe must be callable or expose a transform method")
        except (ValueError, TypeError) as exc:
            raise error_cls(status_code=422, detail=str(exc)) from exc
        if inspect.isawaitable(value):
            value = await value
    return value


# Sentinel returned by run_filters when no filter matched — lets the caller
# re-raise the original exception (preserving traceback) from its except block.
NO_FILTER_MATCH: Any = object()


async def run_filters(
    exc: Exception,
    request: Any,
    filters: Tuple[Any, ...],
    convert: Optional[Callable[[Any], Any]] = None,
) -> Any:
    """
    Route ``exc`` through PyNest ExceptionFilter instances in order.

    The first filter whose ``@Catch`` types match handles the exception — an
    empty ``__caught_exceptions__`` means catch-all. The filter's (optionally
    awaitable) result is passed through ``convert`` when supplied and returned.
    Returns ``NO_FILTER_MATCH`` if nothing matched.
    """
    host = ArgumentsHost(request=request)
    for raw_filter in filters:
        f = raw_filter() if inspect.isclass(raw_filter) else raw_filter
        caught = getattr(f, "__caught_exceptions__", ())
        if not caught or isinstance(exc, caught):
            result = f.catch(exc, host)
            if inspect.isawaitable(result):
                result = await result
            return convert(result) if convert is not None else result
    return NO_FILTER_MATCH


def extract_credentials(connection: Any, security_scheme: Any) -> Any:
    """
    Best-effort credentials extraction for guards that declare a FastAPI-style
    ``security_scheme`` (Bearer / API-key header). ``connection.headers`` is
    expected to be a str-keyed mapping (Litestar ``ASGIConnection``); adapters
    whose native headers differ (e.g. Blacksheep's bytes headers) should pass a
    shim exposing this interface.
    """
    scheme_name = type(security_scheme).__name__
    if scheme_name in ("APIKeyHeader",):
        header_name = getattr(security_scheme.model, "name", "X-API-Key")
        return connection.headers.get(header_name.lower())
    if scheme_name in ("HTTPBearer", "OAuth2PasswordBearer"):
        auth = connection.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            return auth[len("Bearer "):]
        return None
    return None
