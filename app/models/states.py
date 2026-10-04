"""Artifact-declared application states and recovery instructions."""

from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.actions import ActionType
from app.models.targets import Target


class DetectorStrategy(StrEnum):
    """Supported ways to recognize an application state."""

    TEXT = "text"
    URL = "url"
    TITLE = "title"


class RecoveryThen(StrEnum):
    """Where replay continues after performing a recovery action."""

    RECHECK_CHECKPOINT = "recheck_checkpoint"
    RESTART_SEQUENCE = "restart_sequence"
    NEXT_STEP = "next_step"


class StateDetector(BaseModel):
    """One reusable rule for recognizing a webpage state."""

    strategy: DetectorStrategy
    value: str


class BusinessOutcome(BaseModel):
    """A recognized business result that ends the workflow normally."""

    code: str
    detect: StateDetector


class HardFailure(BaseModel):
    """A recognized failure that cannot be recovered automatically."""

    code: str
    detect: StateDetector


class Recovery(BaseModel):
    """An automatic action for leaving a recoverable state."""

    action: ActionType
    target: Target
    then: RecoveryThen
    max_recoveries: int = Field(gt=0)


class RecoverableCondition(BaseModel):
    """A recognized problem with a declared automatic recovery."""

    code: str
    detect: StateDetector
    recovery: Recovery


class StateDeclarations(BaseModel):
    """All application states known by one artifact."""

    business_outcomes: list[BusinessOutcome] = Field(default_factory=list)
    hard_failures: list[HardFailure] = Field(default_factory=list)
    recoverable_conditions: list[RecoverableCondition] = Field(default_factory=list)
