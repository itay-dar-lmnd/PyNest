from __future__ import annotations

from fastapi.responses import JSONResponse

from nest.common.decorators import Res
from nest.common.exceptions import ExceptionFilter, HttpException, ArgumentsHost
from nest.core.decorators.filters import Catch

# Uses nest.http.Request (the new facade) instead of fastapi.Request directly
from nest.http import Request


@Catch(HttpException)
class HttpExceptionFilter(ExceptionFilter):
    async def catch(self, exception: HttpException, host: ArgumentsHost):
        return JSONResponse(
            status_code=exception.status_code,
            content={
                "statusCode": exception.status_code,
                "message": exception.message,
                "error": type(exception).__name__,
            },
        )
