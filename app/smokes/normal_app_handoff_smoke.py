"""Regression: port-8000 workflow resumes the same 55550 browser session."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from httpx import ASGITransport, AsyncClient

import app.evidence as evidence_module
import app.workflows.member_savings as workflow_module
from app.main import app, run_manager, workflow_service
from app.models.runs import MemberSavingsWorkflowRequest, WorkflowMode
from app.runs.session import ControlOwner, RunStatus
from app.surfaces.web_playwright import WebSurfaceAdapter


async def main() -> None:
    """Prove UI resume wakes the production workflow task and finishes replay."""
    original_artifact_directory = workflow_module.ARTIFACT_DIRECTORY
    original_workflow_evidence_directory = workflow_module.EVIDENCE_DIRECTORY
    original_evidence_directory = evidence_module.EVIDENCE_DIRECTORY
    session = None

    with TemporaryDirectory() as temporary_directory:
        temporary_path = Path(temporary_directory)
        workflow_module.ARTIFACT_DIRECTORY = temporary_path / "artifacts"
        workflow_module.EVIDENCE_DIRECTORY = temporary_path / "evidence"
        evidence_module.EVIDENCE_DIRECTORY = temporary_path / "evidence"

        try:
            request = MemberSavingsWorkflowRequest(
                mode=WorkflowMode.MOCK,
                goal="Look up a member and return the savings balance.",
                target_url="http://localhost:8001",
                discovery_member_id="12345",
                replay_member_id="55550",
            )

            # Start the exact service used by the normal port-8000 form/API.
            session = workflow_service.start(request)

            for _attempt in range(1000):
                if session.current_intervention is not None:
                    break
                if session.task is not None and session.task.done():
                    raise AssertionError(f"Workflow ended before intervention: {session.error}")
                await asyncio.sleep(0.01)
            else:
                raise TimeoutError("Normal workflow did not request intervention")

            assert session.status is RunStatus.PAUSED
            assert session.control_owner is ControlOwner.PAUSED
            assert session.task is not None
            assert session.task.done() is False
            assert isinstance(session.surface, WebSurfaceAdapter)
            assert session.surface.page is not None
            original_page = session.surface.page

            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport, base_url="http://control.test", follow_redirects=False
            ) as client:
                # Transfer control without replacing the RunSession or Page.
                take_response = await client.post(f"/operator/runs/{session.run_id}/take-control")
                assert take_response.status_code == 303
                assert session.control_owner is ControlOwner.HUMAN
                assert session.surface.page is original_page

                # Perform the required human step on that same live page.
                await original_page.get_by_role("button", name="Verify Identity").click()
                await original_page.wait_for_url("**/member/55550")

                # Resume redirects to the refreshing status page, not stale UI.
                resume_response = await client.post(f"/operator/runs/{session.run_id}/resume")
                assert resume_response.status_code == 303
                assert resume_response.headers["location"] == (f"/runs/{session.run_id}/view")
                assert session.control_owner is ControlOwner.RESUMING
                assert session.task.done() is False

            # The original Task reclassifies, extracts, completes, and cleans up.
            await asyncio.wait_for(session.task, timeout=10)
            assert session.status is RunStatus.COMPLETED
            assert session.control_owner is ControlOwner.AUTOMATION
            assert session.current_intervention is None
            assert session.result is not None
            assert session.result["outputs"] == {"savings_balance": "$7,880.10"}
            assert session.surface is None

            print("Normal app 55550 handoff passed.")
            print("Same page resumed:", original_page.url.endswith("/member/55550"))
            print("Final output:", session.result["outputs"])
            print("Final status:", session.status)
        finally:
            if session is not None:
                if session.task is not None and not session.task.done():
                    session.task.cancel()
                    await asyncio.gather(session.task, return_exceptions=True)
                if session.surface is not None:
                    await session.surface.close()
                    session.surface = None
                run_manager.sessions.pop(session.run_id, None)

            workflow_module.ARTIFACT_DIRECTORY = original_artifact_directory
            workflow_module.EVIDENCE_DIRECTORY = original_workflow_evidence_directory
            evidence_module.EVIDENCE_DIRECTORY = original_evidence_directory


if __name__ == "__main__":
    asyncio.run(main())
