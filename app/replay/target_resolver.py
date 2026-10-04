"""Resolve saved logical targets against a live application surface."""

from app.models.targets import Target
from app.surfaces.base import SurfaceAdapter


class TargetResolver:
    """Try a target's primary locator followed by its fallbacks."""

    def __init__(self, surface: SurfaceAdapter) -> None:
        self.surface = surface

    async def resolve(self, target: Target) -> object:
        """Return the single live element matching a saved target."""
        locators = [target.primary]
        locators.extend(target.fallbacks)

        for locator in locators:
            element = await self.surface.find(locator)
            if element is not None:
                return element

        raise LookupError("No locator matched the saved target")
