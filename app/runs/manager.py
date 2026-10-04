"""Creation and tracking of background automation runs."""

import asyncio
from uuid import uuid4

from app.runs.session import RunSession, RunStatus, RunType


class RunManager:
    """Own and track active and completed run sessions."""

    def __init__(self) -> None:
        self.sessions: dict[str, RunSession] = {}

    def create_session(self, goal: str, run_type: RunType) -> RunSession:
        """Create, store, and return a new pending run session."""
        session = RunSession(run_id=str(uuid4()), goal=goal, run_type=run_type)
        self.sessions[session.run_id] = session
        return session

    def get_session(self, run_id: str) -> RunSession | None:
        """Return a stored session, or None when the run ID is unknown."""
        return self.sessions.get(run_id)

    def attach_task(self, session: RunSession, task: asyncio.Task[None]) -> None:
        """Attach a started background task to its run session."""
        session.task = task
        session.status = RunStatus.RUNNING

    def complete_session(self, session: RunSession, result: dict[str, object]) -> None:
        """Record successful output and mark a run as completed."""
        session.error = None
        session.result = result
        session.status = RunStatus.COMPLETED

    def fail_session(self, session: RunSession, error: str) -> None:
        """Record an error and mark a run as failed."""
        session.result = None
        session.error = error
        session.status = RunStatus.FAILED

    def cancel_active_tasks(self) -> list[asyncio.Task[None]]:
        """Request cancellation of every unfinished background task."""
        cancelled_tasks: list[asyncio.Task[None]] = []
        for session in self.sessions.values():
            if session.task is not None and not session.task.done():
                session.task.cancel()
                cancelled_tasks.append(session.task)
        return cancelled_tasks

    async def release_terminal_surface(self, session: RunSession) -> None:
        """Close browser resources while retaining lightweight run metadata."""
        terminal_statuses = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ABORTED}
        if session.status not in terminal_statuses:
            raise ValueError("Only a terminal run can release its surface")

        if session.surface is not None:
            await session.surface.close()
            session.surface = None

    async def shutdown(self) -> None:
        """Cancel unfinished work and close every remaining live surface."""
        tasks = self.cancel_active_tasks()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        for session in self.sessions.values():
            if session.surface is not None:
                await session.surface.close()
                session.surface = None
