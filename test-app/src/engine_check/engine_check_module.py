from __future__ import annotations

from nest.core import Module

from src.engine_check.engine_check_controller import EngineCheckController
from src.engine_check.engine_check_service import EngineCheckService


@Module(
    controllers=[EngineCheckController],
    providers=[EngineCheckService],
)
class EngineCheckModule:
    pass
