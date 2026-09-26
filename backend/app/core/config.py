from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_debug: bool = False
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    finlife_api_key: SecretStr | None = None
    db_path: Path = PROJECT_ROOT / "data" / "savings.db"

    extractor_model: str = "gemini-3.7-flash"
    reviewer_model: str = "gemini-3.7-flash"
    online_agent_model: str = "gemini-3.7-flash"
    gemini_api_key: SecretStr | None = None
    gemini_timeout_seconds: float = 30.0

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
