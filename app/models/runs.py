"""API data models for creating and inspecting runs."""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from app.runs.session import RunStatus, RunType


class WorkflowMode(StrEnum):
    """How workflow discovery chooses its next browser action."""

    OPENAI = "openai"
    MOCK = "mock"


class MemberSavingsWorkflowRequest(BaseModel):
    """Inputs for the complete discovery, artifact, and replay workflow."""

    mode: WorkflowMode = WorkflowMode.OPENAI
    goal: str = Field(
        default="Look up the member and return the current savings balance.", min_length=1
    )
    target_url: str = Field(default="http://localhost:8001", min_length=1)
    discovery_member_id: str = Field(default="12345", min_length=1)
    replay_member_id: str = Field(default="67890", min_length=1)

    @model_validator(mode="after")
    def require_different_members(self):
        """Make the replay prove that the compiled artifact is reusable."""
        self.discovery_member_id = self.discovery_member_id.strip()
        self.replay_member_id = self.replay_member_id.strip()
        self.goal = self.goal.strip()
        self.target_url = self.target_url.strip()
        if not self.discovery_member_id or not self.replay_member_id:
            raise ValueError("Member IDs cannot be blank")
        if self.discovery_member_id == self.replay_member_id:
            raise ValueError("Replay member ID must differ from discovery member ID")
        return self


class CreateRunRequest(BaseModel):
    """Data supplied when starting a background run."""

    goal: str


class CreateRunResponse(BaseModel):
    """Immediate response returned after a run is accepted."""

    run_id: str
    status: RunStatus


class RunStatusResponse(BaseModel):
    """Serializable status and output for one stored run."""

    run_id: str
    goal: str
    run_type: RunType
    status: RunStatus
    stage: str
    stage_detail: str
    stage_history: list[str]
    error: str | None
    result: dict[str, object] | None
