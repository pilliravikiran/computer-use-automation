"""Focused tests for the assignment's reusable core behavior."""

from app.evidence import redact_data, redact_text, redact_url
from app.models.actions import ActionType, LLMAction
from app.models.artifacts import Checkpoint
from app.models.observations import ElementObservation, Observation
from app.models.results import StateKind
from app.models.states import (
    BusinessOutcome,
    DetectorStrategy,
    HardFailure,
    StateDeclarations,
    StateDetector,
)
from app.replay.engine import ReplayEngine
from app.replay.state_classifier import StateClassifier
from app.safety.policy import PolicyEngine, RiskLevel


def make_observation(url: str, text: str = "") -> Observation:
    return Observation(url=url, title="Member Management", text=text, elements=[])


def test_runtime_values_replace_artifact_placeholders() -> None:
    engine = object.__new__(ReplayEngine)

    value = engine.resolve_value("/member/{{member_id}}", {"member_id": "67890"})

    assert value == "/member/67890"


def test_missing_runtime_input_is_rejected() -> None:
    engine = object.__new__(ReplayEngine)

    try:
        engine.resolve_value("/member/{{member_id}}", {})
    except KeyError as error:
        assert "member_id" in str(error)
    else:
        raise AssertionError("A missing runtime input should raise KeyError")


def test_state_classifier_distinguishes_expected_results() -> None:
    states = StateDeclarations(
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
    )
    checkpoint = Checkpoint(
        one_of=[StateDetector(strategy=DetectorStrategy.URL, value="/member/*")]
    )
    classifier = StateClassifier()

    missing = classifier.classify(
        states,
        checkpoint,
        make_observation("http://localhost:8001/member/99999", "No member found"),
    )
    denied = classifier.classify(
        states,
        checkpoint,
        make_observation("http://localhost:8001/member/88888", "Permission denied"),
    )
    success = classifier.classify(
        states, checkpoint, make_observation("http://localhost:8001/member/67890")
    )
    unknown = classifier.classify(
        states, checkpoint, make_observation("http://localhost:8001/security-check")
    )

    assert missing.kind is StateKind.BUSINESS_OUTCOME
    assert denied.kind is StateKind.HARD_FAILURE
    assert success.kind is StateKind.HAPPY_PATH
    assert unknown.kind is StateKind.UNKNOWN


def test_policy_blocks_risky_targets() -> None:
    policy = PolicyEngine(
        allowed_actions={ActionType.CLICK},
        target_risks={"Delete": RiskLevel.RISKY},
        allowed_domains={"localhost"},
        allowed_routes=["/*"],
    )
    observation = Observation(
        url="http://localhost:8001/",
        title="Member Management",
        elements=[ElementObservation(ref="e1", role="button", name="Delete")],
    )
    action = LLMAction(action=ActionType.CLICK, target_ref="e1", reason="Delete the member")

    decision = policy.validate_action(action, observation)

    assert decision.allowed is False
    assert decision.risk is RiskLevel.RISKY


def test_evidence_redacts_nested_sensitive_values() -> None:
    data = {
        "expected": {"value": "/member/99999"},
        "items": ["Balance: $2,250.00", "member 67890"],
    }

    redacted = redact_data(data)

    assert redacted == {
        "expected": {"value": "/member/[REDACTED_ID]"},
        "items": ["Balance: [REDACTED_AMOUNT]", "member [REDACTED_ID]"],
    }
    assert redact_url("http://localhost:8001/member/12345?token=secret") == (
        "http://localhost:8001/member/{record_id}"
    )
    assert redact_text("Member 12345 has $5,430.25") == (
        "Member [REDACTED_ID] has [REDACTED_AMOUNT]"
    )
