"""실행 설정. 값은 환경 변수(.env)에서 읽고 코드에 비밀값을 두지 않는다.

LLM 모델·예산·한도의 기본값은 ADR-0007을 따른다.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# OpenAI 추론 강도. 설정이 가장 아래층이므로 여기서 정의하고 specton.llm이 가져다 쓴다.
ReasoningEffort = Literal["low", "medium", "high"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SPECTON_", extra="ignore")

    openai_api_key: SecretStr | None = None
    design_model: str = "gpt-6.1-sol"
    review_model: str = "gpt-6-luna"
    design_reasoning_effort: ReasoningEffort = "medium"
    review_reasoning_effort: ReasoningEffort = "low"

    llm_timeout_seconds: float = Field(default=120, gt=0)
    llm_api_retries: int = Field(default=3, ge=0)
    llm_concurrency: int = Field(default=4, gt=0)
    max_output_tokens: int = Field(default=8_000, gt=0)
    max_tokens_per_run: int = Field(default=400_000, gt=0)
    run_timeout_seconds: int = Field(default=900, gt=0)

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
