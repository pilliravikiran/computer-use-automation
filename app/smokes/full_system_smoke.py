"""One debuggable smoke test covering discovery through deterministic replay."""

import asyncio
from pathlib import Path

from app.config import settings
from app.discovery.agent import DiscoveryAgent
from app.discovery.artifact_compiler import ArtifactCompiler
from app.discovery.recorder import RecordedStep
from app.llm.openai_provider import OpenAILLMProvider
from app.models.actions import ActionType, LLMAction
from app.models.artifacts import ApplicationIdentity
from app.models.results import ReplayStatus
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
from app.runs.session import RunSession, RunType
from app.safety.policy import PolicyEngine, RiskLevel
from app.surfaces.web_playwright import WebSurfaceAdapter

# SECTION 1 — EXAMPLE VALUES
# Discovery teaches the workflow with 12345.
# Replay proves reuse by running the artifact with 67890.
# NEXT: create small reusable helper models.
DISCOVERY_MEMBER_ID = "12345"
REPLAY_MEMBER_ID = "67890"


# SECTION 2 — TARGET HELPER
# A recovery declaration needs a portable description of a button.
# NEXT: declare the application states stored in the artifact.
def button_target(name: str) -> Target:
    """Create a reusable target for a named button."""
    return Target(primary=Locator(strategy=TargetStrategy.ROLE_NAME, role="button", value=name))


# SECTION 3 — ARTIFACT-DECLARED STATES
# These strings belong to the artifact configuration, not ReplayEngine.
# NEXT: use real OpenAI to discover a successful workflow.
def build_state_declarations() -> StateDeclarations:
    """Declare the application states known by this artifact."""
    return StateDeclarations(
        business_outcomes=[
            BusinessOutcome(
                code="MEMBER_NOT_FOUND",
                detect=StateDetector(strategy=DetectorStrategy.TEXT, value="No member found"),
            )
        ],
        hard_failures=[
            HardFailure(
                code="PERMISSION_DENIED",
                detect=StateDetector(strategy=DetectorStrategy.TEXT, value="Permission denied"),
            )
        ],
        recoverable_conditions=[
            RecoverableCondition(
                code="SESSION_EXPIRED",
                detect=StateDetector(
                    strategy=DetectorStrategy.TEXT, value="Session expired. Please sign in again."
                ),
                recovery=Recovery(
                    action=ActionType.CLICK,
                    target=button_target("Restore Session"),
                    then=RecoveryThen.RESTART_SEQUENCE,
                    max_recoveries=1,
                ),
            ),
            RecoverableCondition(
                code="SYSTEM_NOTICE",
                detect=StateDetector(strategy=DetectorStrategy.TEXT, value="System Notice"),
                recovery=Recovery(
                    action=ActionType.CLICK,
                    target=button_target("Continue"),
                    then=RecoveryThen.RECHECK_CHECKPOINT,
                    max_recoveries=1,
                ),
            ),
        ],
    )


# SECTION 4 — REAL OPENAI DISCOVERY
# OpenAI observes the live browser and chooses one action per loop.
# Policy validates every action and Recorder stores the successful trace.
# NEXT: return the recorded trace to the artifact compiler.
async def discover_workflow() -> list[RecordedStep]:
    """Discover one workflow and return its complete recorder steps."""
    if settings.openai_api_key is None:
        raise RuntimeError("Add OPENAI_API_KEY to your .env file first")

    # 4A. Create the live browser and real OpenAI provider.
    # NEXT: create the safety policy.
    discovery_surface = WebSurfaceAdapter(headless=settings.headless)
    provider = OpenAILLMProvider(
        api_key=settings.openai_api_key.get_secret_value(), model=settings.openai_model
    )

    # 4B. Allow safe discovery actions and classify dangerous target names.
    # NEXT: connect provider, browser, and policy through DiscoveryAgent.
    policy = PolicyEngine(
        allowed_actions={
            ActionType.TYPE,
            ActionType.CLICK,
            ActionType.READ,
            ActionType.EXTRACT,
            ActionType.COMPLETE,
        },
        target_risks={
            "Edit": RiskLevel.REVERSIBLE,
            "Delete": RiskLevel.RISKY,
            "Close Account": RiskLevel.IRREVERSIBLE,
        },
    )

    # 4C. DiscoveryAgent owns the observe → decide → validate → act loop.
    # NEXT: open the demo site and ask OpenAI to discover the goal.
    agent = DiscoveryAgent(
        provider=provider,
        surface=discovery_surface,
        policy=policy,
        max_steps=settings.max_discovery_steps,
    )

    try:
        # 4D. Open the real demo page and begin model-guided discovery.
        # NEXT: verify the model included the required EXTRACT action.
        await discovery_surface.open(settings.demo_app_url)
        actions = await agent.discover(
            "Enter member ID 12345, click Lookup, extract the Savings Account value with output_name savings_balance, and then complete."
        )
        print(f"Discovery produced {len(actions)} actions.")
        print(f"Recorder saved {len(agent.recorder.steps)} complete steps.")

        has_extract = False
        for action in actions:
            if action.action is ActionType.EXTRACT:
                has_extract = True
                break
        if not has_extract:
            raise RuntimeError("OpenAI completed without an EXTRACT action")

        # 4E. Find the member-page observation without assuming a step number.
        # NEXT: deliberately test that Close Account is blocked.
        member_observation = None
        for recorded_step in agent.recorder.steps:
            if "/member/" in recorded_step.observation.url:
                member_observation = recorded_step.observation
                break
        if member_observation is None:
            raise RuntimeError("Discovery never observed the member page")

        close_account_ref = None
        for element in member_observation.elements:
            if element.name == "Close Account":
                close_account_ref = element.ref
                break
        if close_account_ref is None:
            raise RuntimeError("Close Account button was not observed")

        close_account_action = LLMAction(
            action=ActionType.CLICK,
            target_ref=close_account_ref,
            reason="Attempt to close the member account.",
        )
        safety_decision = policy.validate_action(close_account_action, member_observation)
        if safety_decision.allowed:
            raise RuntimeError("Policy incorrectly allowed Close Account")
        print(f"Safety blocked Close Account as {safety_decision.risk}.")

        # 4F. Return the observation/action records for compilation.
        # NEXT: close the discovery browser, even if an error occurs.
        return agent.recorder.steps
    finally:
        await discovery_surface.close()


# SECTION 5 — COMPLETE PIPELINE
# Compile the real discovery trace, save/load JSON, and replay with no LLM.
# NEXT: report success or failure through RunManager.
async def run_pipeline(manager: RunManager, session: RunSession) -> None:
    """Run discovery, compilation, save/load, and replay once."""
    try:
        # 5A. Real OpenAI discovery produces RecordedStep objects.
        # NEXT: compile those records into a portable artifact.
        print("\n1. DISCOVERY")
        recorded_steps = await discover_workflow()

        # 5B. Compiler removes temporary refs and parameterizes 12345.
        # NEXT: print the artifact so every compiled field is visible.
        print("\n2. ARTIFACT COMPILATION")
        compiler = ArtifactCompiler(default_timeout_ms=settings.default_timeout_ms)
        artifact_directory = Path("artifacts")
        artifact_name = "get-member-savings-balance"
        artifact_version = compiler.next_version(artifact_name, artifact_directory)
        artifact = compiler.compile(
            name=artifact_name,
            version=artifact_version,
            application=ApplicationIdentity(
                app_family="demo-member-management", app_version="1", entry_path="/"
            ),
            recorded_steps=recorded_steps,
            states=build_state_declarations(),
            parameters={"member_id": DISCOVERY_MEMBER_ID},
        )
        print(artifact.model_dump_json(indent=2))

        # 5C. Save the next version, prove protection, then load its JSON.
        # NEXT: replay the loaded artifact using member 67890.
        print("\n3. VERSIONED SAVE AND LOAD")
        artifact_path = compiler.save(artifact, artifact_directory)
        # Saving the same version again proves that old artifacts are protected.
        try:
            compiler.save(artifact, artifact_directory)
        except FileExistsError:
            print("Duplicate artifact version was blocked.")

        loaded_artifact = compiler.load(artifact_path)
        print(f"Saved permanently: {artifact_path}")

        # 5D. Replay is deterministic: no OpenAI provider is created here.
        # NEXT: close the replay browser and validate its extracted output.
        print("\n4. DETERMINISTIC REPLAY")
        replay_surface = WebSurfaceAdapter(headless=settings.headless)
        replay_engine = ReplayEngine(replay_surface, settle_ms=settings.replay_settle_ms)
        try:
            replay_result = await replay_engine.run(
                artifact=loaded_artifact,
                base_url=settings.demo_app_url,
                inputs={"member_id": REPLAY_MEMBER_ID},
            )
        finally:
            await replay_surface.close()

        # 5E. Verify that replay used 67890 and returned Jane Doe's balance.
        # NEXT: mark the RunSession as completed.
        if replay_result.status is not ReplayStatus.SUCCESS:
            raise RuntimeError(f"Replay did not succeed: {replay_result}")

        expected_balance = "$2250.00"
        outputs = replay_result.outputs
        if outputs.get("savings_balance") != expected_balance:
            raise RuntimeError(f"Expected {expected_balance}, received {outputs}")

        manager.complete_session(
            session,
            result={
                "artifact": str(artifact_path),
                "discovery_member_id": DISCOVERY_MEMBER_ID,
                "replay_member_id": REPLAY_MEMBER_ID,
                "outputs": outputs,
            },
        )
    except Exception as error:
        # 5F. Any unhandled pipeline error marks the same session as failed.
        manager.fail_session(session, str(error))
        raise


# SECTION 6 — PROGRAM ENTRY
# Create one tracked background task and wait for its final status.
# NEXT: asyncio.run(main()) starts this async function at the bottom.
async def main() -> None:
    """Create and track one complete background automation run."""
    manager = RunManager()
    session = manager.create_session(
        goal="Discover once and replay with a different member ID.", run_type=RunType.DISCOVERY
    )

    # create_task starts the pipeline concurrently; attach_task stores it.
    # NEXT: await waits for that task without blocking the event loop.
    task = asyncio.create_task(run_pipeline(manager, session))
    manager.attach_task(session, task)

    print(f"Run started with status: {session.status}")
    await task
    print(f"Run finished with status: {session.status}")
    print(f"Final result: {session.result}")


# SECTION 7 — START ASYNCIO
# This runs only when executing: python -m app.smokes.full_system_smoke
if __name__ == "__main__":
    asyncio.run(main())
