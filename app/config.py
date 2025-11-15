from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API keys
    YOUTUBE_API_KEY: str = Field(default="")
    OPENAI_API_KEY: str | None = None

    # LLM provider settings
    # values: "openai" (incl. OpenAI-compatible via OPENAI_BASE_URL), or "none"
    LLM_PROVIDER: str = Field(default="openai")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")
    # Allow OpenAI-compatible backends (Groq, OpenRouter, Ollama, etc.)
    OPENAI_BASE_URL: str | None = None

    # Tuning
    MAX_YT_RESULTS: int = Field(default=25)
    MAX_SUGGESTIONS: int = Field(default=10)
    REQUESTS_TIMEOUT: int = Field(default=10)

    # Rate limit (e.g. '10/minute')
    RATE_LIMIT: str = Field(default="10/minute")


settings = Settings()
