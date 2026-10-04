"""Validated configuration for the control application."""

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS_DIRECTORY = PROJECT_ROOT / "artifacts"
EVIDENCE_DIRECTORY = PROJECT_ROOT / "evidence"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    control_app_url: str = "http://localhost:8000"
    demo_app_url: str = "http://localhost:8001"
    headless: bool = False
    max_discovery_steps: int = 25
    default_timeout_ms: int = 5000
    replay_settle_ms: int = 4000
    allowed_domains: list[str] = ["localhost", "127.0.0.1"]
    allowed_routes: list[str] = ["/*"]
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4.1-mini"


settings = Settings()
