"""Teach one complete discovery -> saved artifact -> replay lifecycle.

Start the demo portal, then run:

    python -m app.smokes.end_to_end_artifact_replay_smoke

The mock LLM is the only simulated external boundary. Discovery, recording,
compilation, versioning, disk persistence, loading, browser replay, state
classification, extraction, run tracking, and cleanup use production code.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.config import settings
from app.discovery.agent import DiscoveryAgent
from app.discovery.artifact_compiler import ArtifactCompiler
from app.discovery.recorder import DiscoveryRecorder
from app.llm.mock_provider import MockLLMProvider
from app.models.actions import ActionType, LLMAction
from app.models.artifacts import ApplicationIdentity, ArtifactStep, AutomationArtifact, Checkpoint
from app.models.results import ReplayResult, ReplayStatus, StateClassification
from app.models.states import StateDeclarations
from app.replay.engine import ReplayEngine
from app.runs.manager import RunManager
from app.runs.session import RunSession, RunStatus, RunType
from app.safety.policy import PolicyEngine
from app.surfaces.web_playwright import WebSurfaceAdapter

ARTIFACT_DIRECTORY = Path("artifacts/end-to-end-lifecycle")
ARTIFACT_NAME = "get-member-savings-balance-learning"
DISCOVERY_MEMBER_ID = "12345"
EXPECTED_BALANCE = "$5430.25"


def print_stage(
    title: str, production_call: str, input_description: str, expected_result: str
) -> None:
    """Print the debugger context immediately before a production call."""
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    print(f"Production call: {production_call}")
    print(f"Input: {input_description}")
    print(f"Expected: {expected_result}")
    print("Debugger: use Step Into on the next commented call.")


class TeachingReplayEngine(ReplayEngine):
    """Add narration around the real ReplayEngine implementation."""

    def __init__(self, surface: WebSurfaceAdapter, settle_ms: int) -> None:
        super().__init__(surface=surface, settle_ms=settle_ms)
        self.current_step: ArtifactStep | None = None

    async def execute_step(
        self, step: ArtifactStep, inputs: dict[str, str], outputs: dict[str, str]
    ) -> None:
        """Show each saved step, then delegate execution to ReplayEngine."""
        self.current_step = step
        print("\n--- REPLAY STEP EXECUTION ---------------------------------------------")
        print(f"Step: {step.step_id}")
        print(f"Saved action: {step.action}")
        print(f"Saved target: {step.target.model_dump() if step.target else None}")
        print(f"Runtime inputs: {inputs}")
        print("Production call: app/replay/engine.py ReplayEngine.execute_step()")
        print("Expected: TargetResolver finds one element and the action runs once")
        print("Debugger: Step Into the super().execute_step(...) call below.")

        # Real target resolution and action execution happen inside this call.
        await super().execute_step(step, inputs, outputs)

        print(f"Actual: {step.action} executed successfully")
        print(f"Outputs after action: {outputs}")

    async def classify_current_page(
        self, artifact: AutomationArtifact, checkpoint: Checkpoint
    ) -> StateClassification:
        """Narrate the real observation and state-classification boundary."""
        step_id = self.current_step.step_id if self.current_step else "unknown"
        print("\n--- POST-ACTION OBSERVATION AND CLASSIFICATION -----------------------")
        print(f"Step: {step_id}")
        print(f"Resolved checkpoint: {checkpoint.model_dump()}")
        print("Production call: ReplayEngine.classify_current_page()")
        print("Expected: browser observation matches the step checkpoint")
        print("Debugger: Step Into the super().classify_current_page(...) call below.")

        # Real WebSurface observation and StateClassifier execution happen here.
        classification = await super().classify_current_page(artifact, checkpoint)

        # Observe once more only to print the page evidence without changing it.
        observation = await self.surface.observe()
        print(f"Actual URL: {observation.url}")
        print(f"Actual title: {observation.title}")
        print(f"Actual classification: {classification.kind}")
        return classification


async def run_tracked_replay(
    manager: RunManager,
    session: RunSession,
    engine: TeachingReplayEngine,
    artifact: AutomationArtifact,
    replay_inputs: dict[str, str],
    result_holder: list[ReplayResult],
) -> None:
    """Run replay and finish the production session lifecycle."""
    try:
        # Open the artifact entry page and execute every saved step in order.
        result = await engine.run(
            artifact=artifact, base_url=settings.demo_app_url, inputs=replay_inputs, session=session
        )
        result_holder.append(result)

        # Mark the tracked production session completed with the replay result.
        manager.complete_session(session, result.model_dump(mode="json"))
    except Exception as error:
        manager.fail_session(session, str(error))
        raise


async def main() -> None:
    """Execute one complete, beginner-friendly saved-artifact lifecycle."""
    print("=" * 78)
    print("END-TO-END SAVED ARTIFACT LIFECYCLE")
    print("=" * 78)
    print("User task: Find member 12345 and return the Savings Account balance.")
    print("Only the external LLM boundary is mocked; all project behavior is real.")

    # STEP 1 — RECEIVE AND DEFINE THE USER TASK.
    user_task = "Find member 12345 and return the Savings Account balance"
    discovery_parameters = {"member_id": DISCOVERY_MEMBER_ID}
    print_stage(
        "STEP 1 — DEFINE THE USER TASK AND RUNTIME INPUT",
        "ordinary caller input before app/discovery/agent.py",
        f"task={user_task!r}, parameters={discovery_parameters}",
        "one concrete task and one value that can later become {{member_id}}",
    )
    print(f"Actual task: {user_task}")
    print(f"Actual discovery parameters: {discovery_parameters}")

    # STEP 2 — BUILD THE MOCK LLM BOUNDARY AND REAL DISCOVERY COMPONENTS.
    print_stage(
        "STEP 2 — CONFIGURE MOCK-GUIDED REAL DISCOVERY",
        "MockLLMProvider + PolicyEngine + DiscoveryAgent.__init__",
        "TYPE 12345, CLICK Lookup, EXTRACT Savings Account, COMPLETE",
        "deterministic decisions driving the real browser and recorder",
    )
    provider = MockLLMProvider(
        responses=[
            LLMAction(
                action=ActionType.TYPE,
                target_ref="e1",
                value=DISCOVERY_MEMBER_ID,
                reason="Enter the example member ID.",
            ),
            LLMAction(action=ActionType.CLICK, target_ref="e2", reason="Submit the member lookup."),
            LLMAction(
                action=ActionType.EXTRACT,
                target_ref="e4",
                output_name="savings_balance",
                reason="Capture the Savings Account value.",
            ),
            LLMAction(action=ActionType.COMPLETE, reason="The requested balance has been located."),
        ]
    )
    policy = PolicyEngine(
        allowed_actions={ActionType.TYPE, ActionType.CLICK, ActionType.EXTRACT, ActionType.COMPLETE}
    )
    recorder = DiscoveryRecorder()
    discovery_surface = WebSurfaceAdapter(headless=settings.headless)
    agent = DiscoveryAgent(
        provider=provider,
        surface=discovery_surface,
        policy=policy,
        max_steps=settings.max_discovery_steps,
        recorder=recorder,
    )
    print("Actual: mock provider, policy, recorder, surface, and agent are ready")

    # STEP 3 — DISCOVER THE WORKFLOW IN THE REAL BROWSER.
    print_stage(
        "STEP 3 — RUN DISCOVERY AGAINST THE DEMO PORTAL",
        "app/surfaces/web_playwright.py open() then DiscoveryAgent.discover()",
        f"URL={settings.demo_app_url}, goal={user_task!r}",
        "four decisions recorded from live observations",
    )
    try:
        # Open the live application through the production browser adapter.
        await discovery_surface.open(settings.demo_app_url)

        # Observe, decide, apply policy, act, and record through DiscoveryAgent.
        discovery_trace = await agent.discover(user_task)
    finally:
        await discovery_surface.close()
    assert len(discovery_trace) == 4
    assert len(recorder.steps) == 4
    print(f"Actual decisions: {[action.action for action in discovery_trace]}")
    print(f"Actual recorded steps: {len(recorder.steps)}")
    print(f"Actual LLM prompts received: {len(provider.received_prompts)}")

    # STEP 4 — COMPILE RECORDED REFS INTO PORTABLE TARGETS AND CHECKPOINTS.
    print_stage(
        "STEP 4 — COMPILE A COMPLETE PORTABLE ARTIFACT",
        "app/discovery/artifact_compiler.py ArtifactCompiler.compile()",
        "recorded browser refs plus parameter member_id=12345",
        "TYPE, CLICK, and EXTRACT steps with stable targets and checkpoints",
    )
    compiler = ArtifactCompiler(default_timeout_ms=settings.default_timeout_ms)
    next_version = compiler.next_version(ARTIFACT_NAME, ARTIFACT_DIRECTORY)

    # Convert temporary discovery evidence into the production artifact schema.
    artifact = compiler.compile(
        name=ARTIFACT_NAME,
        version=next_version,
        application=ApplicationIdentity(
            app_family="demo-member-management", app_version="1", entry_path="/"
        ),
        recorded_steps=recorder.steps,
        states=StateDeclarations(),
        parameters=discovery_parameters,
    )
    assert len(artifact.steps) == 3
    print(f"Actual artifact name/version: {artifact.name} v{artifact.version}")
    for compiled_step in artifact.steps:
        print(f"  {compiled_step.step_id}: {compiled_step.action}")
        print(f"    target={compiled_step.target.model_dump() if compiled_step.target else None}")
        print(f"    value={compiled_step.value!r}")
        print(f"    checkpoint={compiled_step.checkpoint.model_dump()}")

    # STEP 5 — SAVE A NEW VERSION USING THE REAL ARTIFACT STORE METHODS.
    print_stage(
        "STEP 5 — VERSION AND SAVE THE ARTIFACT",
        "ArtifactCompiler.next_version() then ArtifactCompiler.save()",
        f"directory={ARTIFACT_DIRECTORY}, requested version={next_version}",
        "a new JSON file without overwriting an existing version",
    )

    # Persist the validated model through the compiler's no-overwrite save API.
    saved_artifact_path = compiler.save(artifact, ARTIFACT_DIRECTORY)
    assert saved_artifact_path.exists()
    print(f"Actual saved path: {saved_artifact_path.resolve()}")
    print(f"Actual saved version: {artifact.version}")

    # STEP 6 — LOAD THE EXACT FILE BACK FROM DISK.
    print_stage(
        "STEP 6 — LOAD AND VALIDATE THE SAVED ARTIFACT",
        "ArtifactCompiler.load() -> AutomationArtifact.model_validate_json()",
        f"path={saved_artifact_path}",
        "the same name, version, and three replay steps",
    )

    # Read and validate the exact artifact version just written to disk.
    loaded_artifact = compiler.load(saved_artifact_path)
    assert loaded_artifact == artifact
    print(f"Actual loaded artifact: {loaded_artifact.name} v{loaded_artifact.version}")
    print(f"Actual loaded step count: {len(loaded_artifact.steps)}")

    # STEP 7 — CREATE A REAL TRACKED REPLAY SESSION.
    print_stage(
        "STEP 7 — CREATE THE RUN AND REPLAY SESSION",
        "app/runs/manager.py RunManager.create_session()",
        f"goal={user_task!r}, run_type={RunType.REPLAY}",
        "a stored pending RunSession with an open automation gate",
    )
    manager = RunManager()

    # Create and retain the replay session through the production manager.
    session = manager.create_session(goal=user_task, run_type=RunType.REPLAY)
    assert manager.get_session(session.run_id) is session
    assert session.status is RunStatus.PENDING
    print(f"Actual session status: {session.status}")
    print(f"Actual run type: {session.run_type}")
    print(f"Actual control gate open: {session.control_event.is_set()}")

    # STEP 8 — REPLAY THE RELOADED ARTIFACT THROUGH THE REAL ENGINE.
    replay_inputs = {"member_id": DISCOVERY_MEMBER_ID}
    replay_surface = WebSurfaceAdapter(headless=settings.headless)
    engine = TeachingReplayEngine(surface=replay_surface, settle_ms=settings.replay_settle_ms)
    result_holder: list[ReplayResult] = []
    print_stage(
        "STEP 8 — REPLAY EVERY SAVED STEP",
        "ReplayEngine.run() -> run_steps() -> execute_step()",
        f"artifact={saved_artifact_path.name}, inputs={replay_inputs}",
        f"three happy-path classifications and output {EXPECTED_BALANCE}",
    )

    # Start one background replay task and attach it to the production session.
    replay_task = asyncio.create_task(
        run_tracked_replay(
            manager=manager,
            session=session,
            engine=engine,
            artifact=loaded_artifact,
            replay_inputs=replay_inputs,
            result_holder=result_holder,
        )
    )
    manager.attach_task(session, replay_task)
    print(f"Actual session status after attach: {session.status}")

    # Await the same tracked task while TeachingReplayEngine narrates each step.
    try:
        await replay_task
    except Exception:
        # A failed tracked run is terminal too, so release its live browser.
        await manager.release_terminal_surface(session)
        raise
    assert len(result_holder) == 1
    replay_result = result_holder[0]
    assert replay_result.status is ReplayStatus.SUCCESS
    assert replay_result.outputs == {"savings_balance": EXPECTED_BALANCE}
    print(f"Actual replay status: {replay_result.status}")
    print(f"Actual extracted output: {replay_result.outputs}")

    # STEP 9 — VERIFY COMPLETION AND RELEASE THE BROWSER.
    print_stage(
        "STEP 9 — FINISH THE RUN AND CLEAN UP",
        "RunManager.complete_session() and release_terminal_surface()",
        "successful ReplayResult retained on the tracked session",
        "completed queryable session with no live browser surface",
    )
    assert session.status is RunStatus.COMPLETED
    assert session.result is not None
    assert session.result["outputs"] == {"savings_balance": EXPECTED_BALANCE}
    print(f"Actual completed session result: {session.result}")

    # Close browser resources while keeping lightweight run history queryable.
    await manager.release_terminal_surface(session)
    assert session.surface is None
    assert manager.get_session(session.run_id) is session
    print(f"Actual browser surface after cleanup: {session.surface}")
    print("Actual session remains queryable: True")

    print("\n" + "=" * 78)
    print("END-TO-END SAVED ARTIFACT LIFECYCLE PASSED")
    print("=" * 78)
    print(f"Saved artifact retained for inspection: {saved_artifact_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
