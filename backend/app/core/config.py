from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/acra_db"
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    gemini_api_key: str = ""
    anthropic_api_key: str = ""

    # Browser origins allowed to call this API, comma-separated. The default is the frontend's
    # documented dev port; override it to run the stack anywhere else (a second worktree, an e2e
    # run on a free port, a deployed environment) without editing code.
    cors_origins: str = "http://localhost:3000"

    model_config = {"env_file": ".env", "case_sensitive": False}

    @property
    def cors_origin_list(self) -> list[str]:
        """`cors_origins` split into the list CORSMiddleware expects, ignoring blanks."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
