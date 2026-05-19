from __future__ import annotations

import inspect
import keyword
import typing
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from fastapi import Body as FastAPIBody
from fastapi import Depends
from fastapi import Header as FastAPIHeader
from fastapi import Path as FastAPIPath
from fastapi import Query as FastAPIQuery
from fastapi import Request, Response
from pydantic import TypeAdapter


_MISSING = object()


@dataclass(frozen=True)
class ParamMetadata:
    source: str
    name: Optional[str] = None
    data: Any = None
    factory: Optional[Callable[[Any, "ExecutionContext"], Any]] = None
    pipes: Tuple[Any, ...] = ()
    default: Any = _MISSING


class HttpExecutionContext:
    def __init__(self, request: Request, response: Optional[Response] = None):
        self._request = request
        self._response = response

    def get_request(self) -> Request:
        return self._request

    def get_response(self) -> Optional[Response]:
        return self._response


class ExecutionContext:
    def __init__(self, request: Request, response: Optional[Response] = None):
        self._request = request
        self._response = response

    def switch_to_http(self) -> HttpExecutionContext:
        return HttpExecutionContext(self._request, self._response)

    def get_type(self) -> str:
        return "http"


def Body(key: Optional[str] = None, *pipes: Any, default: Any = _MISSING):
    key, pipes = _normalize_name_and_pipes(key, pipes)
    return ParamMetadata(source="body", name=key, pipes=pipes, default=default)


def Param(name: Optional[str] = None, *pipes: Any, default: Any = _MISSING):
    name, pipes = _normalize_name_and_pipes(name, pipes)
    return ParamMetadata(source="param", name=name, pipes=pipes, default=default)


def Query(name: Optional[str] = None, *pipes: Any, default: Any = _MISSING):
    name, pipes = _normalize_name_and_pipes(name, pipes)
    return ParamMetadata(source="query", name=name, pipes=pipes, default=default)


def Headers(name: Optional[str] = None, *pipes: Any, default: Any = _MISSING):
    name, pipes = _normalize_name_and_pipes(name, pipes)
    return ParamMetadata(source="headers", name=name, pipes=pipes, default=default)


def Req():
    return ParamMetadata(source="request")


def Res():
    return ParamMetadata(source="response")


def Ip(*pipes: Any, default: Any = _MISSING):
    return ParamMetadata(source="ip", pipes=pipes, default=default)


def HostParam(name: Optional[str] = None, *pipes: Any, default: Any = _MISSING):
    name, pipes = _normalize_name_and_pipes(name, pipes)
    return ParamMetadata(source="host", name=name, pipes=pipes, default=default)


def createParamDecorator(factory: Callable[[Any, ExecutionContext], Any]) -> Callable:
    if not callable(factory):
        raise TypeError("createParamDecorator requires a callable factory")

    def decorator(data: Any = None, *pipes: Any, default: Any = _MISSING):
        return ParamMetadata(
            source="custom",
            data=data,
            factory=factory,
            pipes=pipes,
            default=default,
        )

    return decorator


def has_param_decorators(endpoint: Callable) -> bool:
    signature = inspect.signature(endpoint)
    return any(
        isinstance(parameter.default, ParamMetadata)
        for parameter in signature.parameters.values()
    )


def wrap_param_decorators(endpoint: Callable) -> Callable:
    signature = inspect.signature(endpoint)

    # Resolve string annotations produced by `from __future__ import annotations`.
    # get_type_hints() evaluates forward-ref strings in their defining module's
    # namespace so Pydantic/FastAPI receive actual types, not bare strings.
    try:
        resolved_hints = typing.get_type_hints(endpoint)
    except Exception:
        resolved_hints = {}

    wrapped_parameters = []

    for parameter in signature.parameters.values():
        # Substitute resolved annotation where available
        resolved_annotation = resolved_hints.get(parameter.name, parameter.annotation)
        if resolved_annotation is not parameter.annotation:
            parameter = parameter.replace(annotation=resolved_annotation)

        if isinstance(parameter.default, ParamMetadata):
            dependency = _build_dependency(parameter)
            wrapped_parameters.append(
                parameter.replace(
                    annotation=inspect.Parameter.empty,
                    default=Depends(dependency),
                )
            )
        else:
            wrapped_parameters.append(parameter)

    # Resolve return annotation too — FastAPI uses it for response model serialization.
    resolved_return = resolved_hints.get("return", signature.return_annotation)
    wrapper_signature = signature.replace(
        parameters=wrapped_parameters,
        return_annotation=resolved_return,
    )
    handler_param_names = set(signature.parameters)

    async def wrapper(*args, **kwargs):
        call_kwargs = {k: v for k, v in kwargs.items() if k in handler_param_names}
        result = endpoint(*args, **call_kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    wrapper.__name__ = getattr(endpoint, "__name__", "param_decorator_wrapper")
    wrapper.__signature__ = wrapper_signature
    # Propagate resolved annotations so FastAPI's get_type_hints(wrapper) finds
    # actual types rather than forward-ref strings (which can't be resolved from
    # nest/common/decorators.py's module context).
    wrapper.__annotations__ = {k: v for k, v in resolved_hints.items()}
    return wrapper


def _build_dependency(parameter: inspect.Parameter) -> Callable:
    metadata = parameter.default
    annotation = parameter.annotation

    async def dependency(**kwargs):
        value = await _resolve_value(metadata, kwargs)
        value = await _apply_pipes(value, metadata.pipes)
        return _coerce_value(value, annotation)

    dependency.__name__ = f"resolve_{parameter.name}_{metadata.source}"
    dependency.__signature__ = _dependency_signature(parameter, metadata)
    return dependency


async def _resolve_value(metadata: ParamMetadata, kwargs: dict) -> Any:
    request = kwargs.get("request")
    response = kwargs.get("response")

    if metadata.source == "request":
        return request
    if metadata.source == "response":
        return response
    if metadata.source == "param" and metadata.name is None:
        return dict(request.path_params)
    if metadata.source == "query" and metadata.name is None:
        return dict(request.query_params)
    if metadata.source == "headers" and metadata.name is None:
        return dict(request.headers)
    if metadata.source == "ip":
        return request.client.host if request.client else None
    if metadata.source == "host":
        if metadata.name:
            return request.path_params.get(metadata.name)
        return request.url.hostname
    if metadata.source == "custom":
        context = ExecutionContext(request, response)
        result = metadata.factory(metadata.data, context)
        if inspect.isawaitable(result):
            return await result
        return result

    return _first_source_value(kwargs)


def _dependency_signature(
    parameter: inspect.Parameter,
    metadata: ParamMetadata,
) -> inspect.Signature:
    source = metadata.source
    annotation = parameter.annotation

    if source == "request":
        return inspect.Signature(
            parameters=[
                inspect.Parameter(
                    "request",
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=Request,
                )
            ]
        )

    if source == "response":
        return inspect.Signature(
            parameters=[
                inspect.Parameter(
                    "response",
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=Response,
                )
            ]
        )

    if source in {"param", "query", "headers"} and metadata.name is None:
        return _request_only_signature()

    if source in {"ip", "host"}:
        return _request_only_signature()

    if source == "custom":
        return inspect.Signature(
            parameters=[
                inspect.Parameter(
                    "request",
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=Request,
                ),
                inspect.Parameter(
                    "response",
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=Response,
                ),
            ]
        )

    if source == "body":
        name = _source_parameter_name(metadata.name or parameter.name)
        default = _default_value(metadata)
        fastapi_default = FastAPIBody(
            default,
            alias=metadata.name,
            embed=metadata.name is not None,
        )
        return inspect.Signature(
            parameters=[
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=annotation,
                    default=fastapi_default,
                )
            ]
        )

    if source == "param":
        name = _source_parameter_name(metadata.name or parameter.name)
        alias = None if name == (metadata.name or parameter.name) else metadata.name
        fastapi_default = FastAPIPath(..., alias=alias)
        return inspect.Signature(
            parameters=[
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=annotation,
                    default=fastapi_default,
                )
            ]
        )

    if source == "query":
        return _simple_source_signature(
            parameter,
            metadata,
            lambda default, alias: FastAPIQuery(default, alias=alias),
        )

    if source == "headers":
        return _simple_source_signature(
            parameter,
            metadata,
            lambda default, alias: FastAPIHeader(default, alias=alias),
        )

    return inspect.Signature()


def _simple_source_signature(parameter, metadata, marker_factory) -> inspect.Signature:
    source_name = metadata.name or parameter.name
    name = _source_parameter_name(source_name)
    alias = source_name if name != source_name or metadata.name else None
    fastapi_default = marker_factory(_default_value(metadata), alias)

    return inspect.Signature(
        parameters=[
            inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=parameter.annotation,
                default=fastapi_default,
            )
        ]
    )


def _request_only_signature() -> inspect.Signature:
    return inspect.Signature(
        parameters=[
            inspect.Parameter(
                "request",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=Request,
            )
        ]
    )


def _normalize_name_and_pipes(name: Any, pipes: Tuple[Any, ...]):
    if name is not None and not isinstance(name, str):
        return None, (name, *pipes)
    return name, pipes


def _source_parameter_name(name: str) -> str:
    if name.isidentifier() and not keyword.iskeyword(name):
        return name
    return "value"


def _default_value(metadata: ParamMetadata) -> Any:
    if metadata.default is _MISSING:
        return ...
    return metadata.default


def _first_source_value(kwargs: dict) -> Any:
    for key, value in kwargs.items():
        if key not in {"request", "response"}:
            return value
    return None


async def _apply_pipes(value: Any, pipes: Tuple[Any, ...]) -> Any:
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
            from fastapi import HTTPException
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if inspect.isawaitable(value):
            value = await value
    return value


def _coerce_value(value: Any, annotation: Any) -> Any:
    if value is None or annotation in {inspect.Parameter.empty, Any}:
        return value
    if inspect.isclass(annotation) and isinstance(value, annotation):
        return value
    return TypeAdapter(annotation).validate_python(value)
