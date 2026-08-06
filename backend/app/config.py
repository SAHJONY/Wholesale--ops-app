from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./wholesale_ops.db"
    schema_mode: Literal["strict"] = "strict"
    # No upstash_* fields either, for the same reason as bland_* below: nothing
    # reads them. The dependency was removed as unused; the settings outlived
    # it and kept binding UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN,
    # so those could be filled in and have no effect at all.
    #
    # No bland_* fields here on purpose. Declaring them would bind the env names
    # BLAND_API_KEY and BLAND_WEBHOOK_SECRET, which nothing reads -- every call
    # site uses BLAND_AI_*. A field here is an invitation to set the short name,
    # and a short name that is set but unread is a configuration that looks
    # complete and does nothing. That already happened once: the retired
    # /webhooks/bland gated itself on bland_webhook_secret and answered 503 for
    # its whole life.
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
    # Smarty US address verification. Server-side key pair -- the "Embedded
    # key" from the same dashboard is browser-scoped and will not authenticate
    # these calls.
    smarty_auth_id: str | None = None
    smarty_auth_token: str | None = None
    google_maps_api_key: str | None = None
    app_url: str = "http://localhost:3000"


settings = Settings()
