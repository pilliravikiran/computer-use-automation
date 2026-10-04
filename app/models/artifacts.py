"""Models used by reusable automation artifacts."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.models.actions import ActionType
from app.models.states import StateDeclarations, StateDetector
from app.models.targets import Target


class ExtractMode(StrEnum):
    """Supported ways to read a value from a matched element."""

    SELF = "self"
    ADJACENT_CELL = "adjacent_cell"
    SIBLING_TEXT = "sibling_text"
    LABELLED_VALUE = "labelled_value"


class ValueType(StrEnum):
    """Portable data types supported by capability contracts."""

    STRING = "string"


class ArtifactInput(BaseModel):
    """One typed value a calling agent must supply."""

    name: str
    value_type: ValueType = ValueType.STRING
    required: bool = True
    sensitive: bool = True
    description: str = "Runtime input; example values are never persisted."


class ArtifactOutput(BaseModel):
    """One typed value returned by deterministic replay."""

    name: str
    value_type: ValueType = ValueType.STRING
    sensitive: bool = True
    description: str = "Extracted runtime output; values are not stored in the artifact."


class ApplicationIdentity(BaseModel):
    """Portable identity of the application an artifact automates."""

    app_family: str
    app_version: str
    entry_path: str


class Checkpoint(BaseModel):
    """One or more acceptable states after a replay action."""

    one_of: list[StateDetector] = Field(min_length=1)


class ArtifactStep(BaseModel):
    """One deterministic instruction saved in an artifact."""

    step_id: str
    action: ActionType
    target: Target | None = None
    value: str | None = None
    output_name: str | None = None
    extract_mode: ExtractMode | None = None
    timeout_ms: int = Field(gt=0)
    max_attempts: int = Field(gt=0)
    checkpoint: Checkpoint

    @model_validator(mode="after")
    def validate_extract_mode(self) -> Self:
        """Require an extraction mode for every EXTRACT step."""
        if self.action is ActionType.EXTRACT and self.extract_mode is None:
            raise ValueError("extract step requires extract_mode")
        return self


class AutomationArtifact(BaseModel):
    """A portable workflow produced from successful discovery."""

    name: str
    version: int = Field(gt=0)
    application: ApplicationIdentity
    inputs: list[ArtifactInput] = Field(default_factory=list)
    outputs: list[ArtifactOutput] = Field(default_factory=list)
    steps: list[ArtifactStep]
    states: StateDeclarations
