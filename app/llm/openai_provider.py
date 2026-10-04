"""Real language-model provider backed by OpenAI."""

from openai import AsyncOpenAI

from app.llm.base import LLMProvider
from app.models.actions import LLMAction


class OpenAILLMProvider(LLMProvider):
    """Request discovery actions from an OpenAI model."""

    def __init__(self, api_key: str, model: str) -> None:
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY is required")

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def complete(self, prompt: str) -> LLMAction:
        """Return one model-selected action."""
        response = await self.client.responses.parse(
            model=self.model,
            instructions=(
                "Choose exactly one next safe browser action. Use only element references present in the observation. Do not repeat an action that was already performed. Return complete when the goal has been achieved."
            ),
            input=prompt,
            text_format=LLMAction,
        )

        action = response.output_parsed
        if action is None:
            raise RuntimeError("OpenAI did not return a valid action")

        return action
