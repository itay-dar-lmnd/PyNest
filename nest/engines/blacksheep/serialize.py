"""
Response serialization for the Blacksheep adapter.

Approach B (request-extraction wrapper) means the adapter owns serialization
rather than delegating to Blacksheep's handler-return machinery. To stay
byte-compatible with the FastAPI engine (the cross-engine test suite compares
actual JSON), we encode via FastAPI's ``jsonable_encoder`` — already a core
PyNest dependency — then let Blacksheep emit the JSON.
"""
from __future__ import annotations

from typing import Any, Optional

from blacksheep import Response
from blacksheep import json as bs_json
from blacksheep import no_content
from blacksheep.contents import Content
from fastapi.encoders import jsonable_encoder


def _is_blacksheep_response(value: Any) -> bool:
    return isinstance(value, Response)


def _is_starlette_response(value: Any) -> bool:
    # Starlette/FastAPI responses expose .body (bytes) and .status_code but are
    # not Blacksheep Responses.
    return (
        not isinstance(value, Response)
        and hasattr(value, "body")
        and hasattr(value, "status_code")
    )


def to_blacksheep_response(result: Any) -> Optional[Response]:
    """
    Convert a handler/filter result that may be a Starlette/FastAPI Response (or
    plain data) into a Blacksheep Response, preserving status, body, content-type
    and all headers (Location for redirects, Set-Cookie, etc.).

    Used for exception-filter output (PyNest produces a Starlette ``JSONResponse``)
    and for controllers that return Starlette ``HTMLResponse``/``RedirectResponse``
    or set cookies — the same handlers must work unchanged across engines.
    """
    if result is None:
        return None
    if _is_blacksheep_response(result):
        return result
    if _is_starlette_response(result):
        body = result.body
        if not isinstance(body, (bytes, bytearray)):
            body = str(body).encode()
        content_type = result.headers.get("content-type", "application/octet-stream")
        response = Response(
            result.status_code, content=Content(content_type.encode(), bytes(body))
        )
        # Carry every other header (location, set-cookie, ...); Content owns
        # content-type/content-length.
        for key, value in result.headers.items():
            if key.lower() in ("content-type", "content-length"):
                continue
            response.add_header(key.encode(), value.encode())
        return response
    return bs_json(jsonable_encoder(result))


def serialize(result: Any, status_code: Optional[int]) -> Response:
    """
    Turn a handler return value into a Blacksheep Response.

    - Blacksheep Response  → returned as-is (handler set its own status/headers)
    - Starlette Response   → converted (preserving status + JSON body)
    - None                 → 204 when no explicit status, else json null
    - everything else      → ``jsonable_encoder`` then JSON, with the parity
                             default of 200 (see status-code parity in the design)
    """
    if _is_blacksheep_response(result):
        return result
    if _is_starlette_response(result):
        return to_blacksheep_response(result)
    status = status_code or 200
    if result is None:
        return no_content() if status_code is None else bs_json(None, status=status)
    return bs_json(jsonable_encoder(result), status=status)
