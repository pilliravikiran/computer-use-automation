"""Validation of model-selected actions before execution."""

from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatch
from urllib.parse import urlparse

from app.models.actions import ActionType, LLMAction
from app.models.observations import ElementObservation, Observation


class RiskLevel(StrEnum):
    """Safety impact assigned to a proposed operation."""

    SAFE = "safe"
    REVERSIBLE = "reversible"
    RISKY = "risky"
    IRREVERSIBLE = "irreversible"


@dataclass(frozen=True)
class PolicyDecision:
    """Result of checking one proposed action against policy."""

    allowed: bool
    reason: str
    risk: RiskLevel = RiskLevel.SAFE


class PolicyEngine:
    """Check proposed actions against configured safety rules."""

    def __init__(
        self,
        allowed_actions: set[ActionType],
        target_risks: dict[str, RiskLevel] | None = None,
        allowed_domains: set[str] | None = None,
        allowed_routes: list[str] | None = None,
    ) -> None:
        self.allowed_actions = set(allowed_actions)
        self.target_risks: dict[str, RiskLevel] = {}
        self.allowed_domains = allowed_domains
        self.allowed_routes = allowed_routes

        if target_risks is not None:
            for target_name, risk in target_risks.items():
                normalized_name = target_name.casefold()
                self.target_risks[normalized_name] = risk

    def classify_target_risk(self, target: ElementObservation) -> RiskLevel:
        """Return the configured risk level for an observed target."""
        normalized_name = target.name.casefold()
        return self.target_risks.get(normalized_name, RiskLevel.SAFE)

    def find_target(self, action: LLMAction, observation: Observation) -> ElementObservation | None:
        """Find the observed element referenced by an action."""
        if action.target_ref is None:
            return None

        for element in observation.elements:
            if element.ref == action.target_ref:
                return element

        return None

    def validate_target_url(self, url: str) -> PolicyDecision:
        """Enforce configured domain and route boundaries before navigation."""
        parsed_url = urlparse(url)
        if self.allowed_domains is not None and parsed_url.hostname not in self.allowed_domains:
            return PolicyDecision(
                allowed=False, reason=f"Domain is not allowed: {parsed_url.hostname}"
            )

        if self.allowed_routes is not None:
            path = parsed_url.path or "/"
            route_is_allowed = False
            for route in self.allowed_routes:
                if fnmatch(path, route):
                    route_is_allowed = True
                    break

            if not route_is_allowed:
                return PolicyDecision(allowed=False, reason=f"Route is not allowed: {path}")

        return PolicyDecision(allowed=True, reason="Target URL is allowed")

    def validate_action(self, action: LLMAction, observation: Observation) -> PolicyDecision:
        """Approve only action types included in the allowlist."""
        url_decision = self.validate_target_url(observation.url)
        if not url_decision.allowed:
            return url_decision

        if action.action not in self.allowed_actions:
            return PolicyDecision(
                allowed=False, reason=f"Action type is not allowed: {action.action}"
            )

        risk = RiskLevel.SAFE
        if action.target_ref is not None:
            target = self.find_target(action, observation)
            if target is None:
                return PolicyDecision(
                    allowed=False, reason=f"Target does not exist: {action.target_ref}"
                )
            risk = self.classify_target_risk(target)

        if risk in {RiskLevel.RISKY, RiskLevel.IRREVERSIBLE}:
            return PolicyDecision(
                allowed=False, reason=f"Target requires human intervention: {risk}", risk=risk
            )

        return PolicyDecision(
            allowed=True, reason=f"Action type is allowed: {action.action}", risk=risk
        )
