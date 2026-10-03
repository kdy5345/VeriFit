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
    checkpoint_path: Path = PROJECT_ROOT / "data" / "conversations.sqlite"

    extractor_model: str = "gemini-3.7-flash"
    reviewer_model: str = "gemini-3.7-flash"
    online_agent_model: str = "gemini-3.7-flash"
    gemini_api_key: SecretStr | None = None
    gemini_timeout_seconds: float = 30.0

    cache_enabled: bool = True
    redis_url: SecretStr | None = None
    cache_prefix: str = "verifit:v1"
    cache_products_ttl: int = 3600
    cache_calculation_ttl: int = 1800
    cache_llm_ttl: int = 600
    cache_response_ttl: int = 600
    cache_max_entries: int = 512
    cache_max_value_bytes: int = 2_000_000
    cache_memory_max_bytes: int = 32_000_000
    cache_redis_timeout_seconds: float = 0.3

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
