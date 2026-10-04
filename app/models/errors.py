"""Errors that stop automation when a safe choice cannot be made."""


class LowConfidenceTargetError(RuntimeError):
    """Raised when one saved locator matches more than one element."""

    code = "LOW_CONFIDENCE_TARGET"
