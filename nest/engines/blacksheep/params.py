"""
ParamSpec → kwargs extraction for the Blacksheep adapter.

Unlike the FastAPI/Litestar adapters (which rewrite the handler signature so the
framework's own DI populates params), the Blacksheep adapter extracts every
parameter itself from the request inside the route wrapper — Blacksheep's Rodi
DI resolves by type annotation and can't consume PyNest's ParamSpec model.

The ParamSpecs on ``RouteSpec.params`` carry only the source + alias; the
endpoint parameter *name* and *annotation* live on the signature (a ``ParamSpec``
is the parameter's default value). So we inspect the endpoint once at
registration to build a binding plan, then resolve values per request — reads go
through the Starlette-compat facade (str-normalized) and pipes + Pydantic
coercion use the shared helpers.
"""
from __future__ import annotations

import inspect
import typing
from typing import Any, List, NamedTuple, Tuple

from blacksheep import Response as BlacksheepResponse
from blacksheep.exceptions import BadRequest

from nest.engine._shared import apply_pipes as _shared_apply_pipes
from nest.engine._shared import coerce_value
from nest.engine.execution_context import ExecutionContext
from nest.engine.params import ParamSpec


class _Binding(NamedTuple):
    name: str          # the endpoint's python parameter name (the kwargs key)
    annotation: Any    # resolved type hint, or inspect.Parameter.empty
    spec: ParamSpec


def build_param_plan(endpoint) -> List[_Binding]:
    """Inspect ``endpoint`` once and return the (name, annotation, spec) bindings."""
    signature = inspect.signature(endpoint)
    try:
        hints = typing.get_type_hints(endpoint)
    except Exception:
        hints = {}
    plan: List[_Binding] = []
    for parameter in signature.parameters.values():
        if isinstance(parameter.default, ParamSpec):
            annotation = hints.get(parameter.name, parameter.annotation)
            plan.append(_Binding(parameter.name, annotation, parameter.default))
    return plan


async def _apply_pipes(value: Any, pipes: Tuple[Any, ...]) -> Any:
    """Bind the shared pipe runner to Blacksheep's BadRequest for 422-ish rendering."""
    return await _shared_apply_pipes(value, pipes, BadRequest)


def _default(spec: ParamSpec) -> Any:
    # ParamSpec.default is ``...`` (Ellipsis) when the parameter is required.
    return None if spec.default is ... else spec.default


def _coerce(value: Any, annotation: Any) -> Any:
    if annotation is inspect.Parameter.empty:
        return value
    return coerce_value(value, annotation)


def _new_response() -> BlacksheepResponse:
    return BlacksheepResponse(200)


async def extract_params(facade: Any, plan: List[_Binding]) -> dict:
    """
    Resolve handler kwargs from the (Starlette-compat) request facade.

    ``facade`` exposes ``.headers``/``.query_params``/``.path_params``/``.client``
    /``.json()`` with str-normalized values; ``.host`` and native bits are
    reachable via delegation.
    """
    kwargs: dict = {}
    response = None
    for name, annotation, spec in plan:
        if spec.source == "body":
            data = await facade.json()
            val = _coerce(data, annotation)

        elif spec.source == "query":
            if spec.name is None:
                val = dict(facade.query_params.items())
            else:
                raw = facade.query_params.get(spec.name)
                val = _coerce(raw, annotation) if raw is not None else _default(spec)

        elif spec.source == "path":
            raw = facade.path_params.get(spec.name)
            val = _coerce(raw, annotation) if raw is not None else _default(spec)

        elif spec.source == "header":
            if spec.name is None:
                val = dict(facade.headers.items())
            else:
                raw = facade.headers.get(spec.name)
                val = _coerce(raw, annotation) if raw is not None else _default(spec)

        elif spec.source == "request":
            val = facade

        elif spec.source == "response":
            response = response or _new_response()
            val = response

        elif spec.source == "ip":
            val = facade.client.host

        elif spec.source == "host":
            val = facade.host

        elif spec.source == "custom":
            ctx = ExecutionContext(facade, response)
            val = spec.factory(spec.data, ctx)
            if inspect.isawaitable(val):
                val = await val

        else:
            val = _default(spec)

        if spec.pipes:
            val = await _apply_pipes(val, spec.pipes)

        kwargs[name] = val
    return kwargs
