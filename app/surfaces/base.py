"""Base interface for controllable application surfaces."""

from abc import ABC, abstractmethod
from pathlib import Path

from app.models.artifacts import ExtractMode
from app.models.observations import Observation
from app.models.targets import Locator


class SurfaceAdapter(ABC):
    """Blueprint for observing and controlling an application surface."""

    @abstractmethod
    async def open(self, target: str) -> None:
        """Open the application at the supplied target."""
        ...

    @abstractmethod
    async def observe(self) -> Observation:
        """Return a compact structured view of the current surface."""
        ...

    @abstractmethod
    async def resolve_target(self, ref: str) -> object:
        """Resolve a temporary observation reference to a surface target."""
        ...

    @abstractmethod
    async def find(self, locator: Locator) -> object | None:
        """Find one live element using a saved locator."""
        ...

    @abstractmethod
    async def type(self, ref: str, value: str) -> None:
        """Enter text into the element identified by a temporary reference."""
        ...

    @abstractmethod
    async def click(self, ref: str) -> None:
        """Click the element identified by a temporary reference."""
        ...

    @abstractmethod
    async def type_element(self, element: object, value: str, timeout_ms: int) -> None:
        """Enter text into an already-resolved live element."""
        ...

    @abstractmethod
    async def click_element(self, element: object, timeout_ms: int) -> None:
        """Click an already-resolved live element."""
        ...

    @abstractmethod
    async def extract_text(self, element: object, mode: ExtractMode, timeout_ms: int) -> str:
        """Read text from an already-resolved live element."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources owned by the surface."""
        ...

    @abstractmethod
    async def capture_failure_evidence(self, directory: Path, name: str) -> Path | None:
        """Persist a redacted rich signal for debugging a failed run."""
        ...
