from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./wholesale_ops.db"
    schema_mode: Literal["strict"] = "strict"
    upstash_redis_rest_url: str | None = None
    upstash_redis_rest_token: str | None = None
    bland_api_key: str | None = None
    bland_webhook_secret: str | None = None
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5"
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    claude_server_side_fallback: bool = True
    # Second engine. Tried only when Claude is unreachable, so that a provider
    # outage degrades to a different model rather than straight to rule-based
    # analysis. Unset is a valid configuration -- the chain simply gets shorter.
    openai_api_key: str | None = None
    # Override with OPENAI_MODEL to whatever the account actually has access to;
    # this default was not verifiable from the build environment.
    openai_model: str = "gpt-5.1"
    google_maps_api_key: str | None = None
    app_url: str = "http://localhost:3000"


settings = Settings()
