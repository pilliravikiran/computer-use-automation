"""Observe-decide-act loop for workflow discovery."""

import json

from app.discovery.recorder import DiscoveryRecorder
from app.llm.base import LLMProvider
from app.models.actions import ActionType, LLMAction
from app.safety.policy import PolicyEngine
from app.surfaces.base import SurfaceAdapter


class DiscoveryAgent:
    """Use an LLM provider to choose actions on an application surface."""

    def __init__(
        self,
        provider: LLMProvider,
        surface: SurfaceAdapter,
        policy: PolicyEngine,
        max_steps: int,
        recorder: DiscoveryRecorder | None = None,
    ) -> None:
        self.provider = provider
        self.surface = surface
        self.policy = policy
        self.max_steps = max_steps
        if recorder is None:
            recorder = DiscoveryRecorder()
        self.recorder = recorder

    async def discover(self, goal: str) -> list[LLMAction]:
        """Repeat observe, decide, and act until the goal is complete."""
        trace: list[LLMAction] = []
        self.recorder.clear()

        for step_number in range(1, self.max_steps + 1):
            observation = await self.surface.observe()
            if self.recorder.steps:
                self.recorder.record_result(observation)

            previous_actions = "No actions have been performed yet."
            if trace:
                previous_actions = ""
                for previous_action in trace:
                    previous_actions += previous_action.model_dump_json() + "\n"

            model_observation = observation.model_dump(include={"title", "elements"})
            prompt = f"Goal:\n{goal}\n\nStep:\n{step_number}\n\nActions already performed:\n{previous_actions}\nCurrent privacy-minimized observation:\n{json.dumps(model_observation, indent=2)}"
            action = await self.provider.complete(prompt)
            policy_decision = self.policy.validate_action(action, observation)
            if not policy_decision.allowed:
                raise PermissionError(policy_decision.reason)

            self.recorder.record(step_number, observation, action)
            trace.append(action)
            finished = await self.execute_action(action)
            if finished:
                return trace

        raise RuntimeError(f"Discovery exceeded the maximum of {self.max_steps} steps")

    async def execute_action(self, action: LLMAction) -> bool:
        """Execute one supported discovery action."""
        if action.action is ActionType.TYPE:
            if action.target_ref is None or action.value is None:
                raise ValueError("Invalid TYPE action")
            await self.surface.type(action.target_ref, action.value)
            return False

        if action.action is ActionType.CLICK:
            if action.target_ref is None:
                raise ValueError("Invalid CLICK action")
            await self.surface.click(action.target_ref)
            return False

        if action.action in {ActionType.READ, ActionType.EXTRACT}:
            return False

        if action.action is ActionType.COMPLETE:
            return True

        raise ValueError(f"Unsupported action: {action.action}")
