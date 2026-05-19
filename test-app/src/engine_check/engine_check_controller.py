from __future__ import annotations

from nest.core import Controller, Get

from src.engine_check.engine_check_service import EngineCheckService


@Controller("/engine-check", tag="engine-check")
class EngineCheckController:
    def __init__(self, service: EngineCheckService) -> None:
        self.service = service

    @Get("/contracts")
    def contracts(self) -> dict:
        """Returns a live report of every PR-1 contract symbol."""
        return self.service.contracts_report()

    @Get("/adapter")
    def adapter(self) -> dict:
        """Returns the AbstractHttpAdapter abstract-method surface."""
        return self.service.adapter_contract_report()
