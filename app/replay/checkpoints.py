"""Evaluate artifact checkpoints against live observations."""

from fnmatch import fnmatch
from urllib.parse import urlparse

from app.models.artifacts import Checkpoint
from app.models.observations import Observation
from app.models.states import DetectorStrategy, StateDetector


def observation_matches(detector: StateDetector, observation: Observation) -> bool:
    """Return whether one saved detector matches the current page."""
    if detector.strategy is DetectorStrategy.TEXT:
        return detector.value in observation.text

    if detector.strategy is DetectorStrategy.TITLE:
        return detector.value == observation.title

    current_path = urlparse(observation.url).path
    return fnmatch(current_path, detector.value)


def checkpoint_passes(checkpoint: Checkpoint, observation: Observation) -> bool:
    """Return true when the current page matches any expected detector."""
    for detector in checkpoint.one_of:
        if observation_matches(detector, observation):
            return True

    return False
