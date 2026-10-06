"""Redacted, structured evidence emitted by production workflow runs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.config import EVIDENCE_DIRECTORY
from app.discovery.recorder import RecordedStep
from app.models.artifacts import AutomationArtifact
from app.models.intervention import HumanAction
from app.models.results import ReplayResult


def redact_url(url: str) -> str:
    """Remove numeric record identifiers from a URL before persistence."""
    parsed = urlsplit(url)
    redacted_path = re.sub(r"(?<=/)\d{4,}(?=/|$)", "{record_id}", parsed.path)
    return urlunsplit((parsed.scheme, parsed.netloc, redacted_path, "", ""))


def redact_text(value: str) -> str:
    """Remove common record identifiers and financial values from free text."""
    value = re.sub(r"\$[\d,]+(?:\.\d{2})?", "[REDACTED_AMOUNT]", value)
    return re.sub(r"\b\d{4,}\b", "[REDACTED_ID]", value)


def redact_data(value: object) -> object:
    """Redact strings nested inside dictionaries and lists."""
    if isinstance(value, str):
        return redact_text(value)

    if isinstance(value, list):
        redacted_items = []
        for item in value:
            redacted_items.append(redact_data(item))
        return redacted_items

    if isinstance(value, dict):
        redacted_mapping = {}
        for key, item in value.items():
            redacted_mapping[key] = redact_data(item)
        return redacted_mapping

    return value


class EvidenceWriter:
    """Write reviewable evidence without raw typed values or page text."""

    def __init__(self, run_id: str, mode: str) -> None:
        EVIDENCE_DIRECTORY.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.mode = mode

    def write_discovery(self, steps: list[RecordedStep]) -> Path:
        """Persist redacted observe-decide-act records as JSON Lines."""
        path = EVIDENCE_DIRECTORY / f"discovery-{self.run_id}.jsonl"
        lines: list[str] = []
        for step in steps:
            target_role = None
            for element in step.observation.elements:
                if element.ref == step.action.target_ref:
                    target_role = element.role
                    break
            record = {
                "mode": self.mode,
                "step": step.step_number,
                "url": redact_url(step.observation.url),
                "title": step.observation.title,
                "action": step.action.action,
                "reason": redact_text(step.action.reason),
                "target_ref": step.action.target_ref,
                "target_role": target_role,
                "typed_value": "[REDACTED]" if step.action.value else None,
                "result_url": (
                    redact_url(step.result_observation.url) if step.result_observation else None
                ),
            }
            lines.append(json.dumps(record, default=str))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def write_artifact(self, artifact: AutomationArtifact) -> Path:
        """Persist the parameterized, typed capability used by replay."""
        path = EVIDENCE_DIRECTORY / f"artifact-{self.run_id}.json"
        path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        return path

    def write_replay(self, result: ReplayResult) -> Path:
        """Persist replay status and output shape while redacting values."""
        path = EVIDENCE_DIRECTORY / f"replay-{self.run_id}.json"
        redacted_outputs = {}
        for output_name in result.outputs:
            redacted_outputs[output_name] = "[REDACTED]"

        record = {
            "mode": self.mode,
            "status": result.status,
            "output_names": sorted(result.outputs),
            "outputs": redacted_outputs,
            "code": result.code,
            "step_id": result.step_id,
            "recovered": result.recovered,
            "message": redact_data(result.message),
            "expected": redact_data(result.expected),
            "observed": redact_data(result.observed),
        }
        path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        return path

    def write_human_actions(self, actions: list[HumanAction]) -> Path:
        """Persist safe metadata about actions performed during human control."""
        path = EVIDENCE_DIRECTORY / f"human-actions-{self.run_id}.json"
        action_records = []
        for action in actions:
            action_records.append(redact_data(action.model_dump(mode="json")))

        record = {"mode": self.mode, "run_id": self.run_id, "actions": action_records}
        path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
        return path
