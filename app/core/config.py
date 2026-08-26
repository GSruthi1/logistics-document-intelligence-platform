"""
Centralized application settings.

Why this exists: scattering `os.environ.get(...)` calls across modules makes it
impossible to know what config the app actually needs, and it fails silently
(you get `None` instead of a startup error) when something is missing.
pydantic-settings gives us: one source of truth, type validation, and a loud
failure at startup if a required value is missing/malformed — not a mysterious
NoneType error three requests into production.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database ---
    database_url: str = "postgresql+psycopg2://ldip:ldip@localhost:5432/ldip"
    database_url_test: str = "postgresql+psycopg2://ldip:ldip@localhost:5432/ldip_test"

    # --- LLM ---
    llm_provider: Literal["anthropic", "openai"] = "anthropic"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    llm_model_anthropic: str = "claude-sonnet-5"
    llm_model_openai: str = "gpt-4o"

    # --- Routing / confidence ---
    confidence_auto_approve_threshold: float = 0.85

    # --- Storage ---
    storage_backend: Literal["local", "azure_blob"] = "local"
    local_storage_dir: str = "./storage/uploads"
    azure_storage_connection_string: str | None = None
    azure_storage_container: str = "ldip-documents"

    # --- App ---
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Cached so we parse the environment once per process, not per request."""
    return Settings()
