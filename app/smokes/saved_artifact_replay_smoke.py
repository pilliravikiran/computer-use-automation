"""Load the newest saved artifact and replay it without calling OpenAI."""

import argparse
import asyncio
from pathlib import Path

from app.config import ARTIFACTS_DIRECTORY, settings
from app.discovery.artifact_compiler import ArtifactCompiler
from app.models.results import ReplayStatus
from app.replay.engine import ReplayEngine
from app.surfaces.web_playwright import WebSurfaceAdapter

ARTIFACT_NAME = "get-member-savings-balance"
ARTIFACT_DIRECTORY = ARTIFACTS_DIRECTORY


class CountingWebSurfaceAdapter(WebSurfaceAdapter):
    """Count real clicks so the slow-response smoke can prevent duplicates."""

    def __init__(self, headless: bool) -> None:
        super().__init__(headless)
        self.click_count = 0

    async def click_element(self, element: object, timeout_ms: int) -> None:
        self.click_count += 1
        await super().click_element(element, timeout_ms)


def find_newest_artifact() -> Path:
    """Return the saved artifact file with the largest version number."""
    candidates = list(ARTIFACT_DIRECTORY.glob(f"{ARTIFACT_NAME}.v*.json"))
    if not candidates:
        raise FileNotFoundError("No saved artifact exists. Run app.smokes.full_system_smoke first.")

    # Use an ordinary loop instead of passing a function into max().
    # This keeps the version-selection logic visible while debugging.
    newest_artifact = candidates[0]
    newest_version = int(newest_artifact.stem.rsplit(".v", maxsplit=1)[1])

    for candidate in candidates[1:]:
        candidate_version = int(candidate.stem.rsplit(".v", maxsplit=1)[1])
        if candidate_version > newest_version:
            newest_artifact = candidate
            newest_version = candidate_version

    return newest_artifact


async def replay_saved_artifact(member_id: str) -> None:
    """Load the latest artifact and replay it for one member ID."""
    compiler = ArtifactCompiler(default_timeout_ms=settings.default_timeout_ms)
    artifact_path = find_newest_artifact()
    artifact = compiler.load(artifact_path)

    print(f"Loaded artifact: {artifact_path}")
    print(f"Replaying with member_id={member_id}")

    surface = CountingWebSurfaceAdapter(headless=settings.headless)
    engine = ReplayEngine(surface, settle_ms=settings.replay_settle_ms)
    try:
        result = await engine.run(
            artifact=artifact, base_url=settings.demo_app_url, inputs={"member_id": member_id}
        )
        print("Replay result:")
        print(result.model_dump_json(indent=2))

        if member_id == "67890":
            expected_outputs = {"savings_balance": "$2250.00"}
            assert result.status is ReplayStatus.SUCCESS
            assert result.outputs == expected_outputs
            print("Happy replay and state classification passed.")

        elif member_id == "99999":
            assert result.status is ReplayStatus.BUSINESS_OUTCOME
            assert result.code == "MEMBER_NOT_FOUND"
            assert result.step_id == "step_2"
            print("MEMBER_NOT_FOUND business outcome passed.")

        elif member_id == "88888":
            assert result.status is ReplayStatus.FAILURE
            assert result.code == "PERMISSION_DENIED"
            assert result.step_id == "step_2"
            print("PERMISSION_DENIED hard failure passed.")

        elif member_id == "77777":
            assert result.status is ReplayStatus.SUCCESS
            assert result.outputs == {"savings_balance": "$9,420.00"}
            assert result.recovered is True
            assert surface.click_count == 1
            print("Slow lookup recovered with exactly one click.")

        elif member_id == "66666":
            assert result.status is ReplayStatus.SUCCESS
            assert result.outputs == {"savings_balance": "$3,100.00"}
            assert result.recovered is True
            assert surface.click_count == 3
            print("Expired session recovered and sequence restarted.")

        elif member_id == "55555":
            assert result.status is ReplayStatus.SUCCESS
            assert result.outputs == {"savings_balance": "$4,015.75"}
            assert result.recovered is True
            assert surface.click_count == 2
            print("System Notice recovered and checkpoint rechecked.")

        elif member_id == "55550":
            assert result.status is ReplayStatus.HUMAN_REQUIRED
            assert result.code == "UNKNOWN_STATE"
            assert result.step_id == "step_2"
            assert result.outputs == {}
            assert surface.click_count == 1
            print("Unknown page stopped safely for human intervention.")
        else:
            raise ValueError(f"No smoke expectations exist for {member_id}")
    finally:
        await surface.close()


async def main(member_id: str) -> None:
    """Run one saved-artifact scenario selected by member ID."""
    await replay_saved_artifact(member_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("member_id", help="Member ID to replay")
    arguments = parser.parse_args()
    asyncio.run(main(arguments.member_id))
