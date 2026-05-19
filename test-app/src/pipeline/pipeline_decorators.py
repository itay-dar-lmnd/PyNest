from __future__ import annotations

from nest.common.decorators import createParamDecorator, ExecutionContext


# Custom param decorator: extracts X-Request-Id header
RequestId = createParamDecorator(
    lambda data, ctx: ctx.switch_to_http().get_request().headers.get(
        "x-request-id", "unknown"
    )
)

# Custom param decorator: extracts user-agent
UserAgent = createParamDecorator(
    lambda data, ctx: ctx.switch_to_http().get_request().headers.get(
        "user-agent", ""
    )
)

# Custom param decorator: returns all query params as dict
AllQueryParams = createParamDecorator(
    lambda data, ctx: dict(ctx.switch_to_http().get_request().query_params)
)

# Custom param decorator: extracts a specific header by name (data = header name)
def _extract_header(name: str, ctx: ExecutionContext):
    return ctx.switch_to_http().get_request().headers.get(name, "")

ExtractHeader = createParamDecorator(_extract_header)
