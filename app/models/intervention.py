"""Data shown to an operator when automation needs human help."""

from pydantic import BaseModel


class Intervention(BaseModel):
    """One active request for a human to inspect or control a run."""

    run_id: str
    code: str
    reason: str
    step_id: str | None = None
    capability: str
    screenshot_url: str | None = None


class HumanAction(BaseModel):
    """Safe metadata for one action performed during human control."""

    action: str
    tag: str
    role: str
    name: str
    timestamp: str
