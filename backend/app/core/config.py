from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db"
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    # Vision models behind the BOL extractor, primary then fallback. Configurable rather than
    # hardcoded in `ocr_service` so swapping a model is a config change, and so the A8-4 comparison
    # bench reports the model that actually ran instead of a constant duplicated in two places.
    #
    # `gemini-2.5-pro` is the intended upgrade and is a single env var away — GEMINI_MODEL=... —
    # but it is NOT the default, because the project's current API key has **no Pro quota at all**:
    # measured 2026-07-31, Pro returns 429 RESOURCE_EXHAUSTED in ~142 ms on every call while Flash
    # answers in ~2.8 s. Defaulting to Pro would make every receiving upload burn a guaranteed
    # failure before falling back to Claude, so Flash stays the default until the key has Pro quota.
    gemini_model: str = "gemini-2.5-flash"
    anthropic_model: str = "claude-sonnet-4-6"
    # Browser origins allowed to call this API, comma-separated. The default is the frontend's
    # documented dev port; override it to run the stack anywhere else (a second worktree, an e2e
    # run on a free port, a deployed environment) without editing code.
    cors_origins: str = "http://localhost:3000"
    # Request-log format. "text" keeps the human-readable console format developers expect;
    # "json" emits one structured object per line for CI, containers and log shipping. Opt-in
    # rather than default so flipping it is a deliberate deployment choice.
    log_format: str = "text"

    model_config = {"env_file": ".env", "case_sensitive": False}

    @property
    def cors_origin_list(self) -> list[str]:
        """`cors_origins` split into the list CORSMiddleware expects, ignoring blanks."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
