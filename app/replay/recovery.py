"""Execute recovery actions declared in an automation artifact."""

from app.models.actions import ActionType
from app.models.states import Recovery
from app.replay.target_resolver import TargetResolver
from app.surfaces.base import SurfaceAdapter


class RecoveryExecutor:
    """Perform a declared recovery without application-specific logic."""

    def __init__(self, surface: SurfaceAdapter) -> None:
        self.surface = surface
        self.target_resolver = TargetResolver(surface)

    async def execute(self, recovery: Recovery, timeout_ms: int) -> None:
        """Execute one supported recovery action."""
        if recovery.action is not ActionType.CLICK:
            raise NotImplementedError(f"Recovery does not support {recovery.action} yet")

        element = await self.target_resolver.resolve(recovery.target)
        await self.surface.click_element(element, timeout_ms)
