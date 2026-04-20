from typing import Any, Union
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    ollama_host: str = Field(default="")
    ollama_model: str = Field(default="")
    use_ollama: bool = Field(default=False)
    database_url: str = Field(default="")
    redis_url: str | None = Field(default=None, description="Si défini, utilise Redis pour le cache (poster)")
    use_cache: bool = Field(default=True)
    cache_ttl_seconds: int = Field(default=3600)
    pipeline_version: str = Field(default="v2-diff-structured")

    def is_ollama_enabled(self, app_or_request: Any) -> bool:
        """Helper to check if Ollama is enabled, considering overrides in app state."""
        # Handle both FastAPI app and Request objects
        from fastapi import FastAPI, Request
        if isinstance(app_or_request, Request):
            app = app_or_request.app
        else:
            app = app_or_request

        override = getattr(app.state, "use_ollama_override", None)
        if override is None:
            return self.use_ollama
        return bool(override)


settings = Settings()
OLLAMA_URL = f"{settings.ollama_host.rstrip('/')}/api/generate"
