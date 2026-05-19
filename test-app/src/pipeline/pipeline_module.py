from __future__ import annotations

from nest.core import Module

from src.pipeline.pipeline_controller import PipelineController
from src.pipeline.pipeline_service import PipelineService


@Module(
    controllers=[PipelineController],
    providers=[PipelineService],
)
class PipelineModule:
    pass
