"""Common interface for language-model providers."""

from abc import ABC, abstractmethod

from app.models.actions import LLMAction


class LLMProvider(ABC):
    """Blueprint for components that request language-model decisions."""

    @abstractmethod
    async def complete(self, prompt: str) -> LLMAction:
        """Return one validated action for the supplied prompt."""
        ...
