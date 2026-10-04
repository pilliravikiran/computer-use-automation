"""Generic results produced while classifying a replay state."""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.states import Recovery


class StateKind(StrEnum):
    """The possible meanings of an observed application state."""

    BUSINESS_OUTCOME = "business_outcome"
    HARD_FAILURE = "hard_failure"
    RECOVERABLE = "recoverable"
    HAPPY_PATH = "happy_path"
    UNKNOWN = "unknown"


class StateClassification(BaseModel):
    """The classifier's answer for one observed application state."""

    kind: StateKind
    code: str | None = None
    recovery: Recovery | None = None


class ReplayStatus(StrEnum):
    """Final replay results implemented so far."""

    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    FAILURE = "failure"
    HUMAN_REQUIRED = "human_required"
    ABORTED = "aborted"


class ReplayResult(BaseModel):
    """Structured result returned to the caller after replay stops."""

    status: ReplayStatus
    outputs: dict[str, str] = Field(default_factory=dict)
    code: str | None = None
    step_id: str | None = None
    recovered: bool = False
    message: str | None = None
    expected: dict[str, object] | None = None
    observed: dict[str, object] | None = None
