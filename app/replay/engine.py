"""Deterministic execution of compiled automation artifacts."""

import asyncio

from app.intervention.manager import InterventionManager
from app.models.actions import ActionType
from app.models.artifacts import ArtifactStep, AutomationArtifact, Checkpoint
from app.models.results import ReplayResult, ReplayStatus, StateClassification, StateKind
from app.models.states import RecoveryThen, StateDetector
from app.replay.recovery import RecoveryExecutor
from app.replay.state_classifier import StateClassifier
from app.replay.target_resolver import TargetResolver
from app.runs.session import ControlOwner, RunSession, RunStatus
from app.surfaces.base import SurfaceAdapter


class ReplayEngine:
    """Execute saved artifact steps without asking an LLM for decisions."""

    def __init__(self, surface: SurfaceAdapter, settle_ms: int = 4000) -> None:
        if settle_ms <= 0:
            raise ValueError("settle_ms must be positive")

        self.surface = surface
        self.settle_ms = settle_ms
        self.target_resolver = TargetResolver(surface)
        self.recovery_executor = RecoveryExecutor(surface)
        self.state_classifier = StateClassifier()
        self.intervention_manager = InterventionManager()

    async def classify_current_page(
        self, artifact: AutomationArtifact, checkpoint: Checkpoint
    ) -> StateClassification:
        """Observe and classify the page currently shown by the surface."""
        observation = await self.surface.observe()
        return self.state_classifier.classify(
            states=artifact.states, checkpoint=checkpoint, observation=observation
        )

    async def settle_after_timeout(
        self, artifact: AutomationArtifact, checkpoint: Checkpoint
    ) -> StateClassification:
        """Wait for a late result without executing the action again."""
        loop = asyncio.get_running_loop()
        stop_time = loop.time() + (self.settle_ms / 1000)

        while True:
            classification = await self.classify_current_page(artifact, checkpoint)

            if classification.kind is not StateKind.UNKNOWN:
                return classification

            if loop.time() >= stop_time:
                return classification

            await asyncio.sleep(0.1)

    def resolve_value(self, saved_value: str | None, inputs: dict[str, str]) -> str | None:
        """Replace an exact artifact placeholder with its runtime input."""
        if saved_value is None:
            return None

        resolved_value = saved_value
        for input_name, input_value in inputs.items():
            placeholder = "{{" + input_name + "}}"
            resolved_value = resolved_value.replace(placeholder, input_value)

        if "{{" in resolved_value and "}}" in resolved_value:
            raise KeyError(f"Missing replay input for {resolved_value}")

        return resolved_value

    def resolve_checkpoint(self, checkpoint: Checkpoint, inputs: dict[str, str]) -> Checkpoint:
        """Replace input placeholders inside checkpoint detector values."""
        new_detectors: list[StateDetector] = []

        for saved_detector in checkpoint.one_of:
            expected_value = self.resolve_value(saved_detector.value, inputs)
            if expected_value is None:
                raise ValueError("Checkpoint detector value cannot be empty")

            new_detector = StateDetector(strategy=saved_detector.strategy, value=expected_value)
            new_detectors.append(new_detector)

        return Checkpoint(one_of=new_detectors)

    async def execute_step(
        self, step: ArtifactStep, inputs: dict[str, str], outputs: dict[str, str]
    ) -> None:
        """Execute one deterministic artifact step."""
        if step.action is ActionType.TYPE:
            if step.target is None:
                raise ValueError("TYPE step requires a target")

            value = self.resolve_value(step.value, inputs)
            if value is None:
                raise ValueError("TYPE step requires a value")

            element = await self.target_resolver.resolve(step.target)
            await self.surface.type_element(element, value, step.timeout_ms)
            return

        if step.action is ActionType.CLICK:
            if step.target is None:
                raise ValueError("CLICK step requires a target")

            element = await self.target_resolver.resolve(step.target)
            await self.surface.click_element(element, step.timeout_ms)
            return

        if step.action is ActionType.EXTRACT:
            if step.target is None:
                raise ValueError("EXTRACT step requires a target")
            if step.output_name is None:
                raise ValueError("EXTRACT step requires an output name")
            if step.extract_mode is None:
                raise ValueError("EXTRACT step requires an extract mode")

            element = await self.target_resolver.resolve(step.target)
            extracted_text = await self.surface.extract_text(
                element, step.extract_mode, step.timeout_ms
            )
            outputs[step.output_name] = extracted_text
            return

        raise NotImplementedError(f"Replay does not support {step.action} yet")

    async def run_steps(
        self,
        artifact: AutomationArtifact,
        inputs: dict[str, str],
        session: RunSession | None = None,
    ) -> ReplayResult:
        """Execute every artifact step in its saved order."""
        outputs: dict[str, str] = {}
        recovered = False
        recovery_counts: dict[str, int] = {}
        step_index = 0

        while step_index < len(artifact.steps):
            step = artifact.steps[step_index]

            # 1. Fill runtime inputs into this step's saved checkpoint.
            checkpoint = self.resolve_checkpoint(step.checkpoint, inputs)

            # 2. Wait here whenever a human currently owns the run.
            if session is not None:
                await session.control_event.wait()

            # 3. Execute once, then classify the page that appeared.
            try:
                await self.execute_step(step, inputs, outputs)
                classification = await self.classify_current_page(artifact, checkpoint)
            except TimeoutError:
                # The action may have succeeded late. Observe; never repeat it.
                recovered = True
                classification = await self.settle_after_timeout(artifact, checkpoint)

            if classification.kind is StateKind.BUSINESS_OUTCOME:
                return ReplayResult(
                    status=ReplayStatus.BUSINESS_OUTCOME,
                    outputs=outputs,
                    code=classification.code,
                    step_id=step.step_id,
                    recovered=recovered,
                    message="A declared business outcome matched the live page.",
                    expected=checkpoint.model_dump(mode="json"),
                    observed={"state_kind": classification.kind, "code": classification.code},
                )

            if classification.kind is StateKind.HARD_FAILURE:
                return ReplayResult(
                    status=ReplayStatus.FAILURE,
                    outputs=outputs,
                    code=classification.code,
                    step_id=step.step_id,
                    recovered=recovered,
                    message="A declared hard failure matched the live page.",
                    expected=checkpoint.model_dump(mode="json"),
                    observed={"state_kind": classification.kind, "code": classification.code},
                )

            if classification.kind is StateKind.RECOVERABLE:
                recovery = classification.recovery
                recovery_code = classification.code

                if recovery is None or recovery_code is None:
                    raise RuntimeError("Recoverable state has no recovery plan")

                previous_count = recovery_counts.get(recovery_code, 0)
                if previous_count >= recovery.max_recoveries:
                    raise RuntimeError(f"Recovery limit reached for {recovery_code}")

                await self.recovery_executor.execute(recovery, step.timeout_ms)
                recovery_counts[recovery_code] = previous_count + 1
                recovered = True

                if recovery.then is RecoveryThen.RESTART_SEQUENCE:
                    outputs.clear()
                    step_index = 0
                    continue

                if recovery.then is RecoveryThen.NEXT_STEP:
                    step_index += 1
                    continue

                if recovery.then is RecoveryThen.RECHECK_CHECKPOINT:
                    classification = await self.classify_current_page(artifact, checkpoint)

                    if classification.kind is StateKind.HAPPY_PATH:
                        step_index += 1
                        continue

                    raise RuntimeError(
                        f"Checkpoint still failed after recovering {recovery_code}: {classification.kind}"
                    )

                raise NotImplementedError(f"Unknown recovery: {recovery.then}")

            if classification.kind is StateKind.UNKNOWN:
                if session is not None:
                    while classification.kind is StateKind.UNKNOWN:
                        self.intervention_manager.create(
                            session=session,
                            code="UNKNOWN_STATE",
                            reason=(
                                "The current page does not match a declared state. "
                                "Complete the required human step, then resume."
                            ),
                            capability="Inspect the page and complete the unknown dialog.",
                            step_id=step.step_id,
                        )

                        # Keep this same replay Task alive until the operator
                        # resumes this same RunSession and browser page.
                        await session.control_event.wait()
                        classification = await self.classify_current_page(artifact, checkpoint)

                    if classification.kind is StateKind.HAPPY_PATH:
                        session.control_owner = ControlOwner.AUTOMATION
                        session.status = RunStatus.RUNNING
                        session.current_intervention = None
                        step_index += 1
                        continue

                    if classification.kind is StateKind.BUSINESS_OUTCOME:
                        return ReplayResult(
                            status=ReplayStatus.BUSINESS_OUTCOME,
                            outputs=outputs,
                            code=classification.code,
                            step_id=step.step_id,
                            recovered=recovered,
                            message="Human work reached a declared business outcome.",
                            expected=checkpoint.model_dump(mode="json"),
                            observed={
                                "state_kind": classification.kind,
                                "code": classification.code,
                            },
                        )

                    if classification.kind is StateKind.HARD_FAILURE:
                        return ReplayResult(
                            status=ReplayStatus.FAILURE,
                            outputs=outputs,
                            code=classification.code,
                            step_id=step.step_id,
                            recovered=recovered,
                            message="Human work reached a declared hard failure.",
                            expected=checkpoint.model_dump(mode="json"),
                            observed={
                                "state_kind": classification.kind,
                                "code": classification.code,
                            },
                        )

                    raise RuntimeError(
                        "Human-completed page requires automatic recovery; "
                        "replay stopped without repeating the original action."
                    )

                return ReplayResult(
                    status=ReplayStatus.HUMAN_REQUIRED,
                    outputs=outputs,
                    code="UNKNOWN_STATE",
                    step_id=step.step_id,
                    recovered=recovered,
                    message="No declared state explained the observed page.",
                    expected=checkpoint.model_dump(mode="json"),
                    observed={"state_kind": classification.kind},
                )

            if classification.kind is not StateKind.HAPPY_PATH:
                raise RuntimeError(f"Unhandled state: {classification.kind}")

            step_index += 1

        return ReplayResult(status=ReplayStatus.SUCCESS, outputs=outputs, recovered=recovered)

    async def run(
        self,
        artifact: AutomationArtifact,
        base_url: str,
        inputs: dict[str, str],
        session: RunSession | None = None,
    ) -> ReplayResult:
        """Open the artifact entry page and execute its saved steps."""
        target_url = base_url.rstrip("/") + "/" + artifact.application.entry_path.lstrip("/")

        if session is not None:
            session.surface = self.surface

        await self.surface.open(target_url)
        return await self.run_steps(artifact, inputs, session)
