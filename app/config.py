"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings backed by environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(
        default="AI-Powered Website Link Analysis API",
        description="Display name for OpenAPI documentation.",
    )
    app_version: str = Field(
        default="1.0.0",
        description="API semantic version.",
    )

    # LLM configuration (never hardcode secrets; supply via environment or .env)
    gemini_api_key: SecretStr | None = Field(
        default=None,
        description="Google Gemini API key.",
    )
    gemini_model: str = Field(
        default="gemini-4-hydrogen",
        description="Gemini model identifier used for structured analysis.",
    )

    # Safe HTTP fetch limits
    http_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60,
        description="Timeout in seconds for fetching target website content.",
    )
    max_html_bytes: int = Field(
        default=2 * 1024 * 1024,  # 2 MiB
        gt=0,
        description="Maximum HTML response payload size in bytes.",
    )
    max_redirects: int = Field(
        default=5,
        ge=0,
        le=10,
        description="Maximum number of HTTP redirects to follow safely.",
    )
    max_extracted_text_chars: int = Field(
        default=10_000,
        gt=0,
        description="Maximum cleaned text characters forwarded to the LLM.",
    )
    user_agent: str = Field(
        default="WebsiteLinkAnalysisAPI/1.0 (+https://example.com)",
        description="HTTP User-Agent sent when fetching target pages.",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (injectable via FastAPI Depends)."""
    return Settings()
