from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


CANONICAL_APP_URL = "https://wholesale-ops-b89j9ebuu-juan-gonzalezs-projects-94b6dfe9.vercel.app"
CANONICAL_API_URL = f"{CANONICAL_APP_URL}/api/backend"


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
    # OpenAI is used both as the second structured reasoning engine and by the
    # first-class Wholesale Copilot Responses API runtime. ChatGPT web
    # subscriptions do not supply this credential; configure OPENAI_API_KEY on
    # the application deployment.
    openai_api_key: str | None = None
    # Override with OPENAI_MODEL to a Responses-API-capable model available to
    # the API project.
    openai_model: str = "gpt-5.1"
    # Optional OpenAI vector store containing authorized books, SOPs, contracts,
    # market references, and other source material. When unset, the Copilot
    # simply omits file_search rather than pretending the knowledge base exists.
    openai_vector_store_id: str | None = None
    # Smarty US address verification. Server-side key pair -- the "Embedded
    # key" from the same dashboard is browser-scoped and will not authenticate
    # these calls.
    smarty_auth_id: str | None = None
    smarty_auth_token: str | None = None
    google_maps_api_key: str | None = None
    # External/canonical production origins. Vercel's BACKEND_INTERNAL_URL
    # remains the service-to-service transport and must not be replaced with
    # this public URL, which would create a self-proxy loop.
    app_url: str = CANONICAL_APP_URL
    public_api_url: str = CANONICAL_API_URL


settings = Settings()
