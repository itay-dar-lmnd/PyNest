"""
Translation layer: ParamSpec → Litestar param markers.

Mirrors what nest/engines/fastapi/params.py does, but emits Litestar's
``Parameter(query=...)`` / ``Parameter(header=...)`` / ``Body()`` /
``Provide(...)`` primitives instead of FastAPI's Depends/Body/Query/Header.

Litestar reads path params natively from the path (e.g. ``/{item_id:int}``)
without needing a marker on the parameter — but the path string itself must
carry the type. The adapter rewrites ``/items/{item_id}`` → ``/items/{item_id:int}``
based on the ParamSpec annotations before calling ``app.register``.
"""
from __future__ import annotations

import inspect
import typing
from typing import Any, Callable, Optional, Tuple

from litestar.connection import Request as LitestarRequest
from litestar.di import Provide
from litestar.exceptions import HTTPException as LitestarHTTPException
from litestar.params import Body, Parameter
from nest.engine._shared import apply_pipes as _shared_apply_pipes
from nest.engine._shared import coerce_value as _coerce_value
from nest.engine._shared import has_param_specs  # noqa: F401  (re-exported for the adapter)
from nest.engine.execution_context import ExecutionContext
from nest.engine.params import ParamSpec


def bind_params(endpoint: Callable) -> Callable:
    """
    Return a wrapper function with Litestar-flavoured parameter defaults.

    The wrapper's signature exposes Litestar's ``Parameter(query=...)``,
    ``Parameter(header=...)``, ``Body()``, and ``Provide(...)`` markers so
    Litestar's dependency-injection layer populates the values; then the
    wrapper forwards them to the original endpoint.
    """
    signature = inspect.signature(endpoint)

    try:
        resolved_hints = typing.get_type_hints(endpoint)
    except Exception:
        resolved_hints = {}

    wrapped_parameters = []
    extra_dependencies: dict[str, Provide] = {}
    # rename_map: wrapper-param-name → original-endpoint-param-name (for body→data renames).
    rename_map: dict[str, str] = {}

    for parameter in signature.parameters.values():
        original_name = parameter.name
        resolved_annotation = resolved_hints.get(parameter.name, parameter.annotation)
        if resolved_annotation is not parameter.annotation:
            parameter = parameter.replace(annotation=resolved_annotation)

        if isinstance(parameter.default, ParamSpec):
            wrapped_parameter, dep = _build_litestar_parameter(parameter)
            wrapped_parameters.append(wrapped_parameter)
            if wrapped_parameter.name != original_name:
                rename_map[wrapped_parameter.name] = original_name
            if dep is not None:
                # Provide() must be registered on the handler via dependencies={}
                extra_dependencies[wrapped_parameter.name] = dep
        else:
            wrapped_parameters.append(parameter)

    resolved_return = resolved_hints.get("return", signature.return_annotation)
    wrapper_signature = signature.replace(
        parameters=wrapped_parameters,
        return_annotation=resolved_return,
    )
    handler_param_names = set(signature.parameters)

    async def wrapper(*args, **kwargs):
        call_kwargs: dict[str, Any] = {}
        for k, v in kwargs.items():
            if k in handler_param_names:
                call_kwargs[k] = v
            elif k in rename_map:
                call_kwargs[rename_map[k]] = v
        result = endpoint(*args, **call_kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    wrapper.__name__ = getattr(endpoint, "__name__", "litestar_param_wrapper")
    wrapper.__signature__ = wrapper_signature
    # Build __annotations__ from the WRAPPER signature so Litestar's signature
    # parser finds proper types (LitestarRequest, dict, etc.) even when the
    # original endpoint's annotations were missing.
    new_annotations: dict[str, Any] = {}
    for p in wrapped_parameters:
        if p.annotation is not inspect.Parameter.empty:
            new_annotations[p.name] = p.annotation
    if resolved_return is not inspect.Signature.empty:
        new_annotations["return"] = resolved_return
    wrapper.__annotations__ = new_annotations
    # Stash Litestar dependencies so the adapter can pass them to the route decorator.
    wrapper.__litestar_dependencies__ = extra_dependencies  # type: ignore[attr-defined]
    return wrapper


# ── internals ────────────────────────────────────────────────────────────────


_REQUIRED = object()


def _build_litestar_parameter(
    parameter: inspect.Parameter,
) -> tuple[inspect.Parameter, Optional[Provide]]:
    """
    Translate one ParamSpec parameter to a Litestar-shaped Parameter.

    Returns a tuple (rewritten_inspect_parameter, optional_provide). If
    a Provide is returned, it must be attached via the handler's
    ``dependencies={...}`` argument.
    """
    spec: ParamSpec = parameter.default
    annotation = parameter.annotation
    default_value = _default_value(spec)

    if spec.source == "body":
        # Litestar reserves the parameter name 'body' for raw bytes. We rename
        # the wrapper's parameter to 'data' (Litestar's processed-body name)
        # so DTOs and dicts work — the wrapper forwards back to the original
        # endpoint's parameter name via the rename_map.
        marker = Body(default=default_value) if default_value is not _REQUIRED else Body()
        new_name = "data" if parameter.name == "body" else parameter.name
        new_param = inspect.Parameter(
            new_name,
            kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=marker,
            annotation=annotation,
        )
        return new_param, None

    if spec.source == "query":
        # If pipes are present we need to apply them after Litestar extracts the
        # raw value — that requires Provide() rather than a bare Parameter().
        if spec.pipes:
            return _build_provide_for_query(parameter, spec, annotation)
        marker_kwargs: dict[str, Any] = {"query": spec.name or parameter.name}
        if default_value is not _REQUIRED:
            marker_kwargs["default"] = default_value
        marker = Parameter(**marker_kwargs)
        return parameter.replace(default=marker, annotation=annotation), None

    if spec.source == "header":
        if spec.pipes:
            return _build_provide_for_header(parameter, spec, annotation)
        marker_kwargs = {"header": spec.name or parameter.name}
        if default_value is not _REQUIRED:
            marker_kwargs["default"] = default_value
        marker = Parameter(**marker_kwargs)
        return parameter.replace(default=marker, annotation=annotation), None

    if spec.source == "path":
        # Litestar reads {name:type} from the path natively. With pipes, we
        # still need to apply them after extraction.
        if spec.pipes:
            return _build_provide_for_path(parameter, spec, annotation)
        return (
            parameter.replace(default=inspect.Parameter.empty, annotation=annotation),
            None,
        )

    if spec.source == "request":
        # Inject Litestar's Request directly via the parameter annotation.
        return (
            parameter.replace(
                annotation=LitestarRequest,
                default=inspect.Parameter.empty,
            ),
            None,
        )

    if spec.source == "response":
        # Litestar doesn't pre-create a Response object the way FastAPI does.
        # Provide a synthetic one via DI.
        async def provide_response() -> Any:
            from litestar.response import Response
            return Response(content=None, status_code=200)

        return parameter.replace(default=inspect.Parameter.empty), Provide(
            provide_response, sync_to_thread=False
        )

    if spec.source in ("ip", "host", "custom") or (
        spec.source in ("query", "header", "path") and spec.name is None
    ):
        # Need a Provide that consults the request — use DI with a request injection.
        provide_callable = _build_dependency_provider(spec, annotation)
        return parameter.replace(default=inspect.Parameter.empty), Provide(
            provide_callable, sync_to_thread=False
        )

    # Fallback (shouldn't happen — all sources covered above)
    return parameter, None


def _provide_param_name(original: str) -> str:
    """A unique placeholder name to avoid ambiguity with Litestar's auto-inferred params."""
    return f"_piped_{original}"


def _build_provide_for_query(parameter, spec, annotation):
    """When a query param has pipes, build a Provide that extracts then applies them."""
    query_name = spec.name or parameter.name

    async def provide(request: LitestarRequest) -> Any:
        raw = request.query_params.get(query_name)
        if raw is None:
            default = _default_value(spec)
            if default is _REQUIRED:
                raise LitestarHTTPException(status_code=422, detail=f"Missing query parameter '{query_name}'")
            return default
        value = await _apply_pipes(raw, spec.pipes)
        return _coerce_value(value, annotation)

    provide.__name__ = f"provide_query_{query_name}"
    new_name = _provide_param_name(parameter.name)
    new_param = inspect.Parameter(
        new_name,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=annotation,
        default=inspect.Parameter.empty,
    )
    return new_param, Provide(provide, sync_to_thread=False)


def _build_provide_for_header(parameter, spec, annotation):
    header_name = spec.name or parameter.name

    async def provide(request: LitestarRequest) -> Any:
        raw = request.headers.get(header_name)
        if raw is None:
            default = _default_value(spec)
            if default is _REQUIRED:
                raise LitestarHTTPException(status_code=422, detail=f"Missing header '{header_name}'")
            return default
        value = await _apply_pipes(raw, spec.pipes)
        return _coerce_value(value, annotation)

    provide.__name__ = f"provide_header_{header_name}"
    new_name = _provide_param_name(parameter.name)
    new_param = inspect.Parameter(
        new_name,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=annotation,
        default=inspect.Parameter.empty,
    )
    return new_param, Provide(provide, sync_to_thread=False)


def _build_provide_for_path(parameter, spec, annotation):
    path_name = spec.name or parameter.name

    async def provide(request: LitestarRequest) -> Any:
        raw = request.path_params.get(path_name)
        value = await _apply_pipes(raw, spec.pipes)
        return _coerce_value(value, annotation)

    provide.__name__ = f"provide_path_{path_name}"
    new_name = _provide_param_name(parameter.name)
    new_param = inspect.Parameter(
        new_name,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        annotation=annotation,
        default=inspect.Parameter.empty,
    )
    return new_param, Provide(provide, sync_to_thread=False)


def _build_dependency_provider(spec: ParamSpec, annotation: Any) -> Callable:
    """Build a Provide-friendly async function that resolves the value from request."""

    async def resolver(request: LitestarRequest) -> Any:
        value = await _resolve_value_from_request(spec, request)
        value = await _apply_pipes(value, spec.pipes)
        return _coerce_value(value, annotation)

    resolver.__name__ = f"resolve_{spec.source}_{spec.name or 'anon'}"
    return resolver


async def _resolve_value_from_request(spec: ParamSpec, request: LitestarRequest) -> Any:
    if spec.source == "ip":
        return request.client.host if request.client else None
    if spec.source == "host":
        if spec.name:
            return request.path_params.get(spec.name)
        return request.url.hostname
    if spec.source == "query" and spec.name is None:
        return dict(request.query_params)
    if spec.source == "header" and spec.name is None:
        return dict(request.headers)
    if spec.source == "path" and spec.name is None:
        return dict(request.path_params)
    if spec.source == "custom":
        context = ExecutionContext(request)
        result = spec.factory(spec.data, context)
        if inspect.isawaitable(result):
            return await result
        return result
    return None


# ── helpers shared with FastAPI adapter (pipes + coercion) ───────────────────


async def _apply_pipes(value: Any, pipes: Tuple[Any, ...]) -> Any:
    """Bind the shared pipe runner to Litestar's HTTPException for 422 rendering."""
    return await _shared_apply_pipes(value, pipes, LitestarHTTPException)


def _default_value(spec: ParamSpec) -> Any:
    if spec.default is ...:
        return _REQUIRED
    return spec.default


def rewrite_path_with_types(path: str, params: Tuple[ParamSpec, ...]) -> str:
    """
    Rewrite ``/items/{item_id}`` → ``/items/{item_id:int}`` for Litestar.

    Litestar requires path-param types in the URL template itself. PyNest
    routes are framework-neutral (no type in path), so we infer types from
    matching ParamSpecs by name + annotation.
    """
    path_param_specs = {
        spec.name: spec for spec in params
        if spec.source == "path" and spec.name is not None
    }
    if not path_param_specs:
        return path

    out = []
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == "{":
            end = path.find("}", i)
            if end == -1:
                out.append(path[i:])
                break
            inside = path[i + 1:end]
            # Already typed? leave it alone.
            if ":" in inside:
                out.append(path[i:end + 1])
            else:
                name = inside.strip()
                spec = path_param_specs.get(name)
                ls_type = _annotation_to_litestar_path_type(
                    spec.annotation if spec else Any
                )
                out.append("{" + name + ":" + ls_type + "}")
            i = end + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _annotation_to_litestar_path_type(annotation: Any) -> str:
    """Map a Python annotation to a Litestar path-type token (int, str, float, uuid, …)."""
    if annotation in (int,):
        return "int"
    if annotation in (float,):
        return "float"
    if annotation in (bool,):
        return "bool"
    # Defaults to str — Litestar's most permissive type.
    return "str"
