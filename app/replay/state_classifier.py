"""Classify observations using state rules declared in an artifact."""

from app.models.artifacts import Checkpoint
from app.models.observations import Observation
from app.models.results import StateClassification, StateKind
from app.models.states import StateDeclarations
from app.replay.checkpoints import checkpoint_passes, observation_matches


class StateClassifier:
    """Decide what an observed page means without application-specific code."""

    def classify(
        self, states: StateDeclarations, checkpoint: Checkpoint, observation: Observation
    ) -> StateClassification:
        """Classify one observation in the required priority order."""

        # 1. A valid business answer stops replay normally.
        for outcome in states.business_outcomes:
            if observation_matches(outcome.detect, observation):
                return StateClassification(kind=StateKind.BUSINESS_OUTCOME, code=outcome.code)

        # 2. A hard failure stops replay with an error.
        for failure in states.hard_failures:
            if observation_matches(failure.detect, observation):
                return StateClassification(kind=StateKind.HARD_FAILURE, code=failure.code)

        # 3. A recoverable state returns its artifact-declared recovery plan.
        for condition in states.recoverable_conditions:
            if observation_matches(condition.detect, observation):
                return StateClassification(
                    kind=StateKind.RECOVERABLE, code=condition.code, recovery=condition.recovery
                )

        # 4. Only call it happy after no non-happy state matched.
        if checkpoint_passes(checkpoint, observation):
            return StateClassification(kind=StateKind.HAPPY_PATH)

        # 5. Nothing declared explains the observed page.
        return StateClassification(kind=StateKind.UNKNOWN)
