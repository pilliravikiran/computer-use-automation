"""Reusable descriptions for finding application elements."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator


class TargetStrategy(StrEnum):
    """Supported ways to find an element during replay."""

    ROLE_NAME = "role_name"
    LABEL = "label"
    TEXT = "text"
    ATTRIBUTE = "attribute"
    CSS = "css"


class Locator(BaseModel):
    """One saved method for finding an element."""

    strategy: TargetStrategy
    value: str
    role: str | None = None
    attribute: str | None = None

    @model_validator(mode="after")
    def validate_strategy_fields(self) -> Self:
        """Require the extra field needed by certain strategies."""
        if not self.value.strip():
            raise ValueError("locator value cannot be empty")

        if self.strategy is TargetStrategy.ROLE_NAME and self.role is None:
            raise ValueError("role_name strategy requires role")

        if self.strategy is TargetStrategy.ATTRIBUTE and self.attribute is None:
            raise ValueError("attribute strategy requires attribute")

        return self


class Target(BaseModel):
    """Primary and backup instructions for finding one element."""

    primary: Locator
    fallbacks: list[Locator] = Field(default_factory=list)
