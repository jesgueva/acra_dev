from pydantic import model_validator
from pydantic_settings import BaseSettings

DEV_SECRET_KEY = "dev-secret-key-change-in-production"
# HS256 signs with this key directly; below 32 characters it is guessable offline from one token.
MIN_PRODUCTION_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db"
    secret_key: str = DEV_SECRET_KEY
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
    # Skip both vision-LLM providers and return a canned extraction result instead. Opt-in so the
    # receiving/OCR flow is runnable end-to-end (demos, CI, a clean clone) without provisioning
    # GEMINI_API_KEY/ANTHROPIC_API_KEY — never the default, so production behavior is unaffected.
    ocr_mock_mode: bool = False
    # Browser origins allowed to call this API, comma-separated. The default is the frontend's
    # documented dev port; override it to run the stack anywhere else (a second worktree, an e2e
    # run on a free port, a deployed environment) without editing code.
    cors_origins: str = "http://localhost:3000"
    # Request-log format. "text" keeps the human-readable console format developers expect;
    # "json" emits one structured object per line for CI, containers and log shipping. Opt-in
    # rather than default so flipping it is a deliberate deployment choice.
    log_format: str = "text"
    # "production" turns on the startup checks in `_refuse_insecure_production_config`. Railway sets
    # it (.railway/railway.ts); local dev, CI and docker compose leave it at the default, so nothing
    # changes there.
    app_env: str = "development"

    model_config = {"env_file": ".env", "case_sensitive": False}

    @model_validator(mode="after")
    def _refuse_insecure_production_config(self) -> "Settings":
        """Fail closed: a production deploy missing SECRET_KEY must not boot on the public default.

        The default above is committed to the repo, so a JWT signed with it is forgeable by anyone
        who has read the source — and a missing secret would otherwise surface as nothing at all.
        Railway's IaC deliberately ships without secret values, which makes "forgot to set it" a
        real first-deploy state; raising here turns it into a failed deploy (the previous one keeps
        serving) instead.
        """
        if self.app_env.strip().lower() == "production" and (
            self.secret_key == DEV_SECRET_KEY
            or len(self.secret_key) < MIN_PRODUCTION_SECRET_KEY_LENGTH
        ):
            raise ValueError(
                "APP_ENV=production requires SECRET_KEY to be a random value of at least "
                f"{MIN_PRODUCTION_SECRET_KEY_LENGTH} characters (see docs/DEPLOY_RAILWAY.md)"
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        """`cors_origins` split into the list CORSMiddleware expects, ignoring blanks."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
