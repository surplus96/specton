"""실행 설정. 값은 환경 변수(.env)에서 읽고 코드에 비밀값을 두지 않는다."""

from functools import lru_cache

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SPECTON_", extra="ignore")

    openai_api_key: SecretStr | None = None
    design_model: str = "gpt-4o"
    review_model: str = "gpt-4o-mini"

    app_database_url: PostgresDsn = PostgresDsn(
        "postgresql://specton:specton@localhost:5432/specton_app"
    )
    sandbox_database_url: PostgresDsn = PostgresDsn(
        "postgresql://specton_sandbox:specton_sandbox@localhost:5432/specton_sandbox"
    )

    max_upload_mb: int = Field(default=20, gt=0)
    max_structured_retries: int = Field(default=2, ge=0)
    max_rework_iterations: int = Field(default=3, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
