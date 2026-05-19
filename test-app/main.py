from __future__ import annotations

from nest.core import PyNestFactory
from nest.common.exceptions import HttpException
from fastapi.responses import JSONResponse

from src.app_module import AppModule


def create_app():
    app = PyNestFactory.create(
        AppModule,
        title="PyNest PR-1 Test App",
        description=(
            "Smoke-tests every feature touched or introduced in PR 1:\n"
            "- nest.engine contracts (AbstractHttpAdapter, RouteSpec, ParamSpec, …)\n"
            "- nest.http facade (Request, Response, Depends, HTTPException)\n"
            "- Controllers with param decorators (@Body, @Query, @Param, @Headers)\n"
            "- Guards (ApiKeyGuard using nest.http.Request)\n"
            "- Exception filters (HttpExceptionFilter)\n"
            "- Lifecycle hooks (OnApplicationBootstrap, OnApplicationShutdown)\n"
            "- Dependency injection across modules"
        ),
        version="0.1.0",
        docs_url="/docs",
    )

    # Global exception handler for any unfiltered HttpException
    app.use_global_filters(
        __import__(
            "src.items.items_filter", fromlist=["HttpExceptionFilter"]
        ).HttpExceptionFilter()
    )

    return app.get_server()


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
