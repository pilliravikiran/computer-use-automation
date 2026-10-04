"""Typed decisions returned by language-model providers."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, model_validator


class ActionType(StrEnum):
    """Actions the discovery system understands."""

    CLICK = "click"
    TYPE = "type"
    READ = "read"
    EXTRACT = "extract"
    WAIT = "wait"
    NAVIGATE = "navigate"
    COMPLETE = "complete"
    ESCALATE = "escalate"


class LLMAction(BaseModel):
    """One validated next action selected during discovery."""

    action: ActionType
    reason: str
    target_ref: str | None = None
    value: str | None = None
    output_name: str | None = None
    wait_ms: int | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> Self:
        """Require the fields needed by the selected action type."""
        target_actions = {ActionType.CLICK, ActionType.TYPE, ActionType.READ, ActionType.EXTRACT}

        if self.action in target_actions and self.target_ref is None:
            raise ValueError(f"{self.action} requires target_ref")

        if self.action is ActionType.TYPE and self.value is None:
            raise ValueError("type requires value")

        if self.action is ActionType.NAVIGATE and self.value is None:
            raise ValueError("navigate requires a URL in value")

        if self.action is ActionType.EXTRACT and self.output_name is None:
            raise ValueError("extract requires output_name")

        if self.action is ActionType.WAIT and (self.wait_ms is None or self.wait_ms <= 0):
            raise ValueError("wait requires a positive wait_ms")

        return self
