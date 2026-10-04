"""Compile successful discovery records into reusable artifacts."""

from pathlib import Path
from urllib.parse import urlparse

from app.discovery.recorder import RecordedStep
from app.models.actions import ActionType
from app.models.artifacts import (
    ApplicationIdentity,
    ArtifactInput,
    ArtifactOutput,
    ArtifactStep,
    AutomationArtifact,
    Checkpoint,
    ExtractMode,
)
from app.models.states import DetectorStrategy, StateDeclarations, StateDetector
from app.models.targets import Locator, Target, TargetStrategy


class ArtifactCompiler:
    """Convert temporary discovery information into portable steps."""

    def __init__(self, default_timeout_ms: int) -> None:
        if default_timeout_ms <= 0:
            raise ValueError("default_timeout_ms must be positive")

        self.default_timeout_ms = default_timeout_ms

    def parameterize_value(self, value: str | None, parameters: dict[str, str]) -> str | None:
        """Replace a discovered example value with an input placeholder."""
        if value is None:
            return None

        parameterized_value = value
        for parameter_name, example_value in parameters.items():
            if example_value:
                placeholder = "{{" + parameter_name + "}}"
                parameterized_value = parameterized_value.replace(example_value, placeholder)

        return parameterized_value

    def build_target(self, recorded_step: RecordedStep) -> Target | None:
        """Replace an action's temporary ref with a reusable target."""
        target_ref = recorded_step.action.target_ref
        if target_ref is None:
            return None

        matched_element = None
        for element in recorded_step.observation.elements:
            if element.ref == target_ref:
                matched_element = element
                break

        if matched_element is None:
            raise ValueError(f"Target ref {target_ref} was not observed")

        primary = Locator(
            strategy=TargetStrategy.ROLE_NAME, role=matched_element.role, value=matched_element.name
        )
        fallback = Locator(strategy=TargetStrategy.TEXT, value=matched_element.name)

        return Target(primary=primary, fallbacks=[fallback])

    def compile_step(self, recorded_step: RecordedStep, parameters: dict[str, str]) -> ArtifactStep:
        """Convert one recorded discovery step into a portable step."""
        # Temporary browser references become stable primary/fallback locators.
        target = self.build_target(recorded_step)
        # The post-action page becomes the checkpoint for this saved step.
        checkpoint = self.build_checkpoint(recorded_step, parameters)
        value = self.parameterize_value(recorded_step.action.value, parameters)
        extract_mode = None
        if recorded_step.action.action is ActionType.EXTRACT:
            extract_mode = ExtractMode.LABELLED_VALUE

        return ArtifactStep(
            step_id=f"step_{recorded_step.step_number}",
            action=recorded_step.action.action,
            target=target,
            value=value,
            output_name=recorded_step.action.output_name,
            extract_mode=extract_mode,
            timeout_ms=self.default_timeout_ms,
            max_attempts=1,
            checkpoint=checkpoint,
        )

    def build_checkpoint(
        self, recorded_step: RecordedStep, parameters: dict[str, str]
    ) -> Checkpoint:
        """Create a portable URL checkpoint from the post-action page."""
        result = recorded_step.result_observation
        if result is None:
            raise ValueError(f"Step {recorded_step.step_number} has no result observation")

        result_path = urlparse(result.url).path
        result_path = self.parameterize_value(result_path, parameters)
        if result_path is None:
            raise ValueError("Checkpoint path cannot be empty")
        detector = StateDetector(strategy=DetectorStrategy.URL, value=result_path)
        return Checkpoint(one_of=[detector])

    def compile(
        self,
        name: str,
        application: ApplicationIdentity,
        recorded_steps: list[RecordedStep],
        states: StateDeclarations,
        parameters: dict[str, str],
        version: int = 1,
    ) -> AutomationArtifact:
        """Compile an entire discovery trace into one artifact."""
        artifact_steps: list[ArtifactStep] = []

        for recorded_step in recorded_steps:
            if recorded_step.action.action in {ActionType.READ, ActionType.COMPLETE}:
                continue

            artifact_step = self.compile_step(recorded_step, parameters)
            next_step_number = len(artifact_steps) + 1
            artifact_step.step_id = f"step_{next_step_number}"
            artifact_steps.append(artifact_step)

        artifact_inputs = []
        for input_name in parameters:
            artifact_inputs.append(ArtifactInput(name=input_name))

        output_names = set()
        for step in artifact_steps:
            if step.output_name is not None:
                output_names.add(step.output_name)

        artifact_outputs = []
        for output_name in sorted(output_names):
            artifact_outputs.append(ArtifactOutput(name=output_name))

        return AutomationArtifact(
            name=name,
            version=version,
            application=application,
            inputs=artifact_inputs,
            outputs=artifact_outputs,
            steps=artifact_steps,
            states=states,
        )

    def save(self, artifact: AutomationArtifact, directory: Path) -> Path:
        """Save a new artifact version without overwriting an old one."""
        directory.mkdir(parents=True, exist_ok=True)

        filename = f"{artifact.name}.v{artifact.version}.json"
        artifact_path = directory / filename

        if artifact_path.exists():
            raise FileExistsError(f"Artifact already exists: {artifact_path}")

        artifact_path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return artifact_path

    def load(self, artifact_path: Path) -> AutomationArtifact:
        """Load and validate one saved artifact JSON file."""
        artifact_json = artifact_path.read_text(encoding="utf-8")
        return AutomationArtifact.model_validate_json(artifact_json)

    def next_version(self, name: str, directory: Path) -> int:
        """Return the first version number that has not been saved yet."""
        version = 1
        while (directory / f"{name}.v{version}.json").exists():
            version += 1
        return version
