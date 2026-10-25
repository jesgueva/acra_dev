from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db"
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    anthropic_api_key: str = ""
    # Vision models behind the BOL extractor, primary then fallback. Configurable rather than
    # hardcoded in `ocr_service` so swapping a model is a config change, and so the A8-4 comparison
    # bench reports the model that actually ran instead of a constant duplicated in two places.
    #
    # Haiku is the primary because BOL extraction is a high-volume, latency-sensitive extraction
    # task — Haiku's workload — at a fraction of Sonnet's price. Sonnet catches what Haiku cannot:
    # an error, a refusal, or a document it returns no header fields for. If the A8-4 bench shows
    # Haiku below the recorded floor, promote Sonnet with ANTHROPIC_MODEL=claude-sonnet-5-5 and
    # ANTHROPIC_FALLBACK_MODEL= (empty disables the fallback).
    anthropic_model: str = "claude-haiku-5-5"
    anthropic_fallback_model: str = "claude-sonnet-5-5"
    # How hard the model thinks before answering: low | medium | high | xhigh | max. Applies to
    # both models. `medium` is Haiku 5.5's own default, set explicitly so a model swap cannot
    # silently change it; sweep it with the bench before moving it.
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    # Skip the vision models and return a canned extraction result instead. Opt-in so the
    # receiving/OCR flow is runnable end-to-end (demos, CI, a clean clone) without provisioning
    # ANTHROPIC_API_KEY — never the default, so production behavior is unaffected.
    ocr_mock_mode: bool = False
    # Browser origins allowed to call this API, comma-separated. The default is the frontend's
    # documented dev port; override it to run the stack anywhere else (a second worktree, an e2e
    # run on a free port, a deployed environment) without editing code.
    cors_origins: str = "http://localhost:3000"
    # Request-log format. "text" keeps the human-readable console format developers expect;
    # "json" emits one structured object per line for CI, containers and log shipping. Opt-in
    # rather than default so flipping it is a deliberate deployment choice.
    log_format: str = "text"

    # `extra: ignore` so a `.env` still carrying a retired key (GEMINI_API_KEY, GEMINI_MODEL from
    # before OCR went Claude-only) loads instead of failing startup with `extra_forbidden`.
    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}

    @property
    def cors_origin_list(self) -> list[str]:
        """`cors_origins` split into the list CORSMiddleware expects, ignoring blanks."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
