from pathlib import Path
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_prefix="REPORT_", extra="ignore")

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5-unsloth-q6:latest"
    database_url: str = f"sqlite:///{PROJECT_ROOT / 'data' / 'reports.db'}"
    output_dir: Path = PROJECT_ROOT / "data" / "generated"
    prompts_dir: Path = PROJECT_ROOT / "prompts"
    templates_dir: Path = PROJECT_ROOT / "templates"

    @field_validator("ollama_url")
    @classmethod
    def only_local_ollama(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ollama URL must point to the local machine")
        return value.rstrip("/")
