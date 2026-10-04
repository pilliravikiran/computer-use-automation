"""Records what discovery observed and decided at each step."""

from pydantic import BaseModel

from app.models.actions import LLMAction
from app.models.observations import Observation


class RecordedStep(BaseModel):
    """One observation and the action selected from it."""

    step_number: int
    observation: Observation
    action: LLMAction
    result_observation: Observation | None = None


class DiscoveryRecorder:
    """Collect the steps produced during one discovery run."""

    def __init__(self) -> None:
        self.steps: list[RecordedStep] = []

    def clear(self) -> None:
        """Remove steps left from an earlier discovery run."""
        self.steps.clear()

    def record_result(self, observation: Observation) -> None:
        """Save the page observed after the most recent action."""
        if not self.steps:
            raise RuntimeError("There is no recorded action awaiting a result")

        self.steps[-1].result_observation = observation

    def record(self, step_number: int, observation: Observation, action: LLMAction) -> RecordedStep:
        """Create and save one recorded discovery step."""
        recorded_step = RecordedStep(
            step_number=step_number, observation=observation, action=action
        )
        self.steps.append(recorded_step)
        return recorded_step
