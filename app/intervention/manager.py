"""Creation of human-intervention requests for paused runs."""

from app.models.intervention import Intervention
from app.runs.session import ControlOwner, RunSession, RunStatus


class InterventionManager:
    """Pause a run and attach the reason that needs human help."""

    def create(
        self,
        session: RunSession,
        code: str,
        reason: str,
        capability: str,
        step_id: str | None = None,
    ) -> Intervention:
        """Create and store one intervention on the supplied session."""
        intervention = Intervention(
            run_id=session.run_id, code=code, reason=reason, step_id=step_id, capability=capability
        )

        session.current_intervention = intervention
        session.control_event.clear()
        session.control_owner = ControlOwner.PAUSED
        session.status = RunStatus.PAUSED

        return intervention

    def abort(self, session: RunSession) -> None:
        """End a paused run without executing its blocked action."""
        if session.task is not None and not session.task.done():
            session.task.cancel()

        session.control_event.clear()
        session.control_owner = ControlOwner.PAUSED
        session.status = RunStatus.ABORTED
        session.result = {"status": "aborted", "code": "OPERATOR_ABORTED"}
