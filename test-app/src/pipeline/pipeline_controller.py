from __future__ import annotations

from typing import Any

from nest.core import Controller, Get, HttpCode, Post
from nest.common.decorators import Body, Ip, Param, Query, Req

from src.pipeline.pipeline_decorators import (
    AllQueryParams,
    ExtractHeader,
    RequestId,
    UserAgent,
)
from src.pipeline.pipeline_pipes import ClampPipe, PositiveIntPipe, TrimPipe, UpperPipe
from src.pipeline.pipeline_service import PipelineService


@Controller("/pipeline", tag="pipeline")
class PipelineController:
    def __init__(self, service: PipelineService) -> None:
        self.service = service

    # ── pipe demos ─────────────────────────────────────────────────────

    @Get("/trim")
    def trim_query(
        self,
        text: str = Query("text", TrimPipe(), UpperPipe()),
    ) -> dict:
        return self.service.record({"op": "trim_upper", "result": text})

    @Get("/clamp/{value}")
    def clamp_path(
        self,
        value: int = Param("value", ClampPipe(1, 100)),
    ) -> dict:
        return self.service.record({"op": "clamp", "result": value})

    @Get("/positive")
    def positive_query(
        self,
        n: int = Query("n", PositiveIntPipe()),
    ) -> dict:
        return self.service.record({"op": "positive", "result": n})

    # ── custom param decorator demos ────────────────────────────────────

    @Get("/request-id")
    def get_request_id(
        self,
        rid: str = RequestId(),
    ) -> dict:
        return {"request_id": rid}

    @Get("/user-agent")
    def get_user_agent(
        self,
        ua: str = UserAgent(),
    ) -> dict:
        return {"user_agent": ua}

    @Get("/query-dump")
    def dump_all_query(
        self,
        params: dict = AllQueryParams(),
    ) -> dict:
        return {"all_params": params}

    @Get("/header/{name}")
    def extract_header(
        self,
        name: str = Param("name"),
        value: str = ExtractHeader("x-custom"),
    ) -> dict:
        return {"header_name": name, "header_value": value}

    # ── Req() / Ip() injection demos ────────────────────────────────────

    @Get("/ip")
    def get_client_ip(
        self,
        ip: Any = Ip(),
    ) -> dict:
        return {"ip": ip}

    @Get("/method")
    def get_method(
        self,
        request: Any = Req(),
    ) -> dict:
        return {"method": request.method, "url": str(request.url)}

    # ── async endpoints ─────────────────────────────────────────────────

    @Get("/compute/{n}")
    async def async_compute(
        self,
        n: int = Param("n", PositiveIntPipe()),
    ) -> dict:
        return await self.service.slow_computation(n)

    @Post("/batch")
    @HttpCode(201)
    async def async_batch(
        self,
        body: list = Body(),
    ) -> dict:
        results = []
        for item in body:
            r = await self.service.slow_computation(int(item))
            results.append(r)
        return {"count": len(results), "results": results}

    # ── log endpoint ────────────────────────────────────────────────────

    @Get("/log")
    def get_log(self) -> list:
        return self.service.get_log()
