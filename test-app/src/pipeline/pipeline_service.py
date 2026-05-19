from __future__ import annotations

import asyncio
from nest.core import Injectable


@Injectable
class PipelineService:
    def __init__(self) -> None:
        self._log: list[dict] = []

    def record(self, entry: dict) -> dict:
        self._log.append(entry)
        return entry

    def get_log(self) -> list[dict]:
        return list(self._log)

    async def slow_computation(self, n: int) -> dict:
        """Simulates async work — used for concurrency stress testing."""
        await asyncio.sleep(0.01)
        return {"input": n, "result": n * n, "async": True}
