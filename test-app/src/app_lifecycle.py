from __future__ import annotations

from nest.core import Injectable
from nest.common.interfaces import OnApplicationBootstrap, OnApplicationShutdown


@Injectable
class AppLifecycleService(OnApplicationBootstrap, OnApplicationShutdown):
    """Exercises lifecycle hooks — OnApplicationBootstrap and OnApplicationShutdown."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def on_application_bootstrap(self) -> None:
        self.started = True
        print("[lifecycle] Application bootstrapped ✓")

    async def on_application_shutdown(self, signal: str | None = None) -> None:
        self.stopped = True
        print(f"[lifecycle] Application shutting down (signal={signal}) ✓")
