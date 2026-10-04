"""Live state owned by one automation run."""

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum

from app.models.intervention import HumanAction, Intervention
from app.surfaces.base import SurfaceAdapter


class RunStatus(StrEnum):
    """Allowed lifecycle states for an automation run."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class RunType(StrEnum):
    """Kinds of automation work a run can perform."""

    DISCOVERY = "discovery"
    REPLAY = "replay"
    WORKFLOW = "workflow"


class ControlOwner(StrEnum):
    """Who currently controls the live automation session."""

    AUTOMATION = "automation"
    PAUSED = "paused"
    HUMAN = "human"
    RESUMING = "resuming"


def create_open_control_event() -> asyncio.Event:
    """Create a gate that initially allows automation to run."""
    event = asyncio.Event()
    event.set()
    return event


@dataclass
class RunSession:
    """Mutable runtime state for one automation run."""

    run_id: str
    goal: str
    run_type: RunType
    status: RunStatus = RunStatus.PENDING
    control_event: asyncio.Event = field(default_factory=create_open_control_event)
    control_owner: ControlOwner = ControlOwner.AUTOMATION
    task: asyncio.Task[None] | None = None
    current_intervention: Intervention | None = None
    surface: SurfaceAdapter | None = None
    human_actions: list[HumanAction] = field(default_factory=list)
    error: str | None = None
    result: dict[str, object] | None = None
    stage: str = "queued"
    stage_detail: str = "Waiting for the workflow task to start."
    stage_history: list[str] = field(default_factory=list)
