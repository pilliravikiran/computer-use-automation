"""Predictable language-model provider for local tests."""

from app.llm.base import LLMProvider
from app.models.actions import LLMAction


class MockLLMProvider(LLMProvider):
    """Return responses supplied in advance instead of calling an API."""

    def __init__(self, responses: list[LLMAction]) -> None:
        self.responses = list(responses)
        self.received_prompts: list[str] = []

    async def complete(self, prompt: str) -> LLMAction:
        """Record the prompt and return the next prepared response."""
        self.received_prompts.append(prompt)
        if not self.responses:
            raise RuntimeError("MockLLMProvider has no responses remaining")
        return self.responses.pop(0)
