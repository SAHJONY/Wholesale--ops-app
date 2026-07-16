from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./wholesale_ops.db"
    upstash_redis_rest_url: str | None = None
    upstash_redis_rest_token: str | None = None
    bland_api_key: str | None = None
    bland_webhook_secret: str | None = None
    anthropic_api_key: str | None = None
    claude_model: str = "claude-sonnet-4-20250514"
    google_maps_api_key: str | None = None
    app_url: str = "http://localhost:3000"


settings = Settings()
