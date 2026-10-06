"""Orchestrate discovery, artifact persistence, and deterministic replay."""

from __future__ import annotations

import asyncio

from app.config import ARTIFACTS_DIRECTORY, settings
from app.discovery.agent import DiscoveryAgent
from app.discovery.artifact_compiler import ArtifactCompiler
from app.discovery.recorder import DiscoveryRecorder
from app.evidence import EVIDENCE_DIRECTORY, EvidenceWriter
from app.llm.base import LLMProvider
from app.llm.mock_provider import MockLLMProvider
from app.llm.openai_provider import OpenAILLMProvider
from app.models.actions import ActionType, LLMAction
from app.models.artifacts import ApplicationIdentity
from app.models.results import ReplayStatus
from app.models.runs import MemberSavingsWorkflowRequest, WorkflowMode
from app.models.states import (
    BusinessOutcome,
    DetectorStrategy,
    HardFailure,
    RecoverableCondition,
    Recovery,
    RecoveryThen,
    StateDeclarations,
    StateDetector,
)
from app.models.targets import Locator, Target, TargetStrategy
from app.replay.engine import ReplayEngine
from app.runs.manager import RunManager
from app.runs.session import RunSession, RunStatus, RunType
from app.safety.policy import PolicyEngine, RiskLevel
from app.surfaces.web_playwright import WebSurfaceAdapter

ARTIFACT_DIRECTORY = ARTIFACTS_DIRECTORY / "normal-app"
ARTIFACT_NAME = "member-savings-workflow"


def button_target(name: str) -> Target:
    """Build one stable, reviewable button target for recovery."""
    return Target(primary=Locator(strategy=TargetStrategy.ROLE_NAME, role="button", value=name))


def build_state_declarations() -> StateDeclarations:
    """Declare the workflow's business, failure, and recovery taxonomy."""
    member_not_found = BusinessOutcome(
        code="MEMBER_NOT_FOUND",
        detect=StateDetector(strategy=DetectorStrategy.TEXT, value="No member found"),
    )
    permission_denied = HardFailure(
        code="PERMISSION_DENIED",
        detect=StateDetector(strategy=DetectorStrategy.TEXT, value="Permission denied"),
    )
    session_expired = RecoverableCondition(
        code="SESSION_EXPIRED",
        detect=StateDetector(
            strategy=DetectorStrategy.TEXT,
            value="Session expired. Please sign in again.",
        ),
        recovery=Recovery(
            action=ActionType.CLICK,
            target=button_target("Restore Session"),
            then=RecoveryThen.RESTART_SEQUENCE,
            max_recoveries=1,
        ),
    )
    system_notice = RecoverableCondition(
        code="SYSTEM_NOTICE",
        detect=StateDetector(strategy=DetectorStrategy.TEXT, value="System Notice"),
        recovery=Recovery(
            action=ActionType.CLICK,
            target=button_target("Continue"),
            then=RecoveryThen.RECHECK_CHECKPOINT,
            max_recoveries=1,
        ),
    )

    return StateDeclarations(
        business_outcomes=[member_not_found],
        hard_failures=[permission_denied],
        recoverable_conditions=[session_expired, system_notice],
    )


class MemberSavingsWorkflowService:
    """Run the assignment workflow behind both browser UI and JSON API."""

    def __init__(self, run_manager: RunManager) -> None:
        self.run_manager = run_manager

    def start(self, request: MemberSavingsWorkflowRequest) -> RunSession:
        """Create a tracked session and start its workflow in the background."""
        session = self.run_manager.create_session(goal=request.goal, run_type=RunType.WORKFLOW)
        task = asyncio.create_task(self.run(session, request))
        self.run_manager.attach_task(session, task)
        return session

    def update_stage(self, session: RunSession, stage: str, detail: str) -> None:
        """Publish beginner-readable progress for the status UI and API."""
        session.stage = stage
        session.stage_detail = detail
        session.stage_history.append(f"{stage}: {detail}")

    def create_provider(self, request: MemberSavingsWorkflowRequest) -> LLMProvider:
        """Create the selected discovery provider without exposing credentials."""
        if request.mode is WorkflowMode.OPENAI:
            if settings.openai_api_key is None:
                raise ValueError(
                    "OPENAI_API_KEY is not configured. Choose credential-free mock mode or configure the key and restart the control app."
                )
            return OpenAILLMProvider(
                api_key=settings.openai_api_key.get_secret_value(), model=settings.openai_model
            )

        responses = [
            LLMAction(
                action=ActionType.TYPE,
                target_ref="e1",
                value=request.discovery_member_id,
                reason="Enter the discovery member ID.",
            ),
            LLMAction(
                action=ActionType.CLICK,
                target_ref="e2",
                reason="Submit the member lookup.",
            ),
            LLMAction(
                action=ActionType.EXTRACT,
                target_ref="e4",
                output_name="savings_balance",
                reason="Capture the Savings Account value.",
            ),
            LLMAction(
                action=ActionType.COMPLETE,
                reason="The savings balance workflow is fully demonstrated.",
            ),
        ]
        return MockLLMProvider(responses=responses)

    async def run(self, session: RunSession, request: MemberSavingsWorkflowRequest) -> None:
        """Execute the complete production workflow and retain its final result."""
        discovery_surface: WebSurfaceAdapter | None = None
        evidence = EvidenceWriter(session.run_id, str(request.mode))
        try:
            self.update_stage(
                session,
                "discovery_setup",
                f"Preparing {request.mode} discovery for member {request.discovery_member_id}.",
            )
            provider = self.create_provider(request)
            recorder = DiscoveryRecorder()
            allowed_actions = {
                ActionType.TYPE,
                ActionType.CLICK,
                ActionType.READ,
                ActionType.EXTRACT,
                ActionType.COMPLETE,
            }
            target_risks = {
                "Edit": RiskLevel.REVERSIBLE,
                "Delete": RiskLevel.RISKY,
                "Close Account": RiskLevel.IRREVERSIBLE,
            }
            policy = PolicyEngine(
                allowed_actions=allowed_actions,
                target_risks=target_risks,
                allowed_domains=set(settings.allowed_domains),
                allowed_routes=settings.allowed_routes,
            )
            discovery_surface = WebSurfaceAdapter(headless=settings.headless)

            agent = DiscoveryAgent(
                provider=provider,
                surface=discovery_surface,
                policy=policy,
                max_steps=settings.max_discovery_steps,
                recorder=recorder,
            )
            target_decision = policy.validate_target_url(request.target_url)
            if not target_decision.allowed:
                raise PermissionError(target_decision.reason)

            self.update_stage(
                session,
                "discovering",
                "The discovery agent is observing the real portal and choosing actions.",
            )
            await discovery_surface.open(request.target_url)
            discovery_goal = f"{request.goal} Use discovery member {request.discovery_member_id}, identify the Savings Account row, use EXTRACT with output_name savings_balance, then return COMPLETE."
            discovery_trace = await agent.discover(discovery_goal)
            discovery_evidence_path = evidence.write_discovery(recorder.steps)
            await discovery_surface.close()
            discovery_surface = None
            session.surface = None

            self.update_stage(
                session,
                "compiling",
                "Converting temporary browser references into a portable artifact.",
            )
            compiler = ArtifactCompiler(default_timeout_ms=settings.default_timeout_ms)
            artifact_version = compiler.next_version(ARTIFACT_NAME, ARTIFACT_DIRECTORY)
            artifact = compiler.compile(
                name=ARTIFACT_NAME,
                version=artifact_version,
                application=ApplicationIdentity(
                    app_family="demo-member-management", app_version="1", entry_path="/"
                ),
                recorded_steps=recorder.steps,
                states=build_state_declarations(),
                parameters={"member_id": request.discovery_member_id},
            )
            if not artifact.steps:
                raise RuntimeError("Discovery did not produce replayable artifact steps")

            self.update_stage(
                session,
                "saving_artifact",
                f"Saving artifact version {artifact.version} without overwriting.",
            )
            artifact_path = compiler.save(artifact, ARTIFACT_DIRECTORY)
            artifact_evidence_path = evidence.write_artifact(artifact)

            self.update_stage(
                session,
                "loading_artifact",
                f"Reloading and validating {artifact_path.name} from disk.",
            )
            loaded_artifact = compiler.load(artifact_path)

            self.update_stage(
                session,
                "replaying",
                f"Replaying the saved artifact for different member {request.replay_member_id}.",
            )
            replay_surface = WebSurfaceAdapter(headless=settings.headless)
            replay_engine = ReplayEngine(
                surface=replay_surface, settle_ms=settings.replay_settle_ms
            )
            replay_result = await replay_engine.run(
                artifact=loaded_artifact,
                base_url=request.target_url,
                inputs={"member_id": request.replay_member_id},
                session=session,
            )
            replay_evidence_path = evidence.write_replay(replay_result)

            human_evidence_path = None
            if session.human_actions:
                human_evidence_path = evidence.write_human_actions(session.human_actions)

            if replay_result.status is ReplayStatus.HUMAN_REQUIRED:
                raise RuntimeError(
                    "Tracked replay returned HUMAN_REQUIRED instead of waiting on its RunSession control gate."
                )

            evidence_paths = {
                "discovery": str(discovery_evidence_path.resolve()),
                "artifact": str(artifact_evidence_path.resolve()),
                "replay": str(replay_evidence_path.resolve()),
            }
            if human_evidence_path is not None:
                evidence_paths["human_actions"] = str(human_evidence_path.resolve())

            if replay_result.status is ReplayStatus.FAILURE:
                failure_path = await replay_surface.capture_failure_evidence(
                    EVIDENCE_DIRECTORY, f"failure-{session.run_id}"
                )
                if failure_path is not None:
                    evidence_paths["failure"] = str(failure_path.resolve())

            result = {
                "mode": request.mode,
                "discovery_member_id": request.discovery_member_id,
                "replay_member_id": request.replay_member_id,
                "discovery_actions": len(discovery_trace),
                "artifact_path": str(artifact_path.resolve()),
                "artifact_version": loaded_artifact.version,
                "artifact_steps": len(loaded_artifact.steps),
                "replay_status": replay_result.status,
                "outcome_code": replay_result.code,
                "outputs": replay_result.outputs,
                "replay_result": replay_result.model_dump(mode="json"),
                "human_actions": [
                    action.model_dump(mode="json") for action in session.human_actions
                ],
                "evidence": evidence_paths,
            }

            if replay_result.status is ReplayStatus.FAILURE:
                error = f"Replay stopped with code {replay_result.code} at {replay_result.step_id}"
                self.update_stage(session, "failed", error)
                self.run_manager.fail_session(session, error, result)
                return

            self.update_stage(
                session,
                "completed",
                "Discovery, artifact persistence, reload, and replay all completed.",
            )
            self.run_manager.complete_session(session, result)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - background runs retain failures
            failure_surface = session.surface or discovery_surface
            if failure_surface is not None:
                await failure_surface.capture_failure_evidence(
                    EVIDENCE_DIRECTORY, f"failure-{session.run_id}"
                )
            self.update_stage(session, "failed", "The workflow stopped with an error.")
            self.run_manager.fail_session(session, str(error))
        finally:
            if discovery_surface is not None:
                await discovery_surface.close()

            if session.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ABORTED}:
                await self.run_manager.release_terminal_surface(session)
