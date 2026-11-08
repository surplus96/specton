"""실행 설정. 값은 환경 변수(.env)에서 읽고 코드에 비밀값을 두지 않는다.

LLM 모델·예산·한도의 기본값은 ADR-0007을 따른다.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, PostgresDsn, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# OpenAI 추론 강도. 설정이 가장 아래층이므로 여기서 정의하고 specton.llm이 가져다 쓴다.
ReasoningEffort = Literal["low", "medium", "high"]
# 리뷰어 실행 방식 (ADR-0008). parallel은 관점마다 1회, combined는 전체 1회 호출한다.
ReviewMode = Literal["parallel", "combined"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SPECTON_", extra="ignore")

    openai_api_key: SecretStr | None = None
    design_model: str = "gpt-6.1-sol"
    review_model: str = "gpt-6-luna"
    design_reasoning_effort: ReasoningEffort = "medium"
    review_reasoning_effort: ReasoningEffort = "low"
    review_mode: ReviewMode = "combined"

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

    # 실제 DDL 생성·검증·저장 연결(#17)에 맞춰 최종 SQL 승인 검사를 기본으로 켠다.
    # 명시적으로 끄는 호환 모드에서도 승인 근거(approval_basis)는 남긴다 (#167, #195)
    require_sql_validation: bool = True

    # 실행기·lease 시작값 (ADR-0012). 연결 풀은 동시 실행 수, lease 갱신, API 요청을 합쳐 잡는다.
    run_concurrency: int = Field(default=2, gt=0)
    lease_seconds: int = Field(default=60, gt=0)
    lease_renew_seconds: int = Field(default=20, gt=0)
    db_pool_size: int = Field(default=10, gt=0)
    # 실행기가 `queued`·lease 만료 run을 찾는 간격 (ADR-0012)
    runner_poll_seconds: float = Field(default=1.0, gt=0)

    # 업로드 원문·산출물 저장 위치(git 제외). 응답에는 경로를 넣지 않는다 (docs/11).
    storage_dir: Path = Path("var/storage")
    pack_root: Path = Path("domain_packs")
    # SSE가 새 이벤트를 확인하는 간격. 확인할 때만 DB 연결을 빌린다 (ADR-0012).
    sse_poll_seconds: float = Field(default=1.0, gt=0)

    max_upload_mb: int = Field(default=20, gt=0)
    # xlsx·hwpx 압축을 푼 크기 합의 한도. 압축 폭탄을 파서 전에 막는다 (#21)
    max_unzipped_mb: int = Field(default=200, gt=0)
    # HTTPS로 배포하면 켠다. 세션 쿠키에 Secure를 붙여 HTTP로 보내지 않는다 (#21, PR #108 리뷰)
    session_cookie_secure: bool = False
    max_structured_retries: int = Field(default=2, ge=0)
    max_rework_iterations: int = Field(default=3, ge=0)

    @model_validator(mode="after")
    def _check_runner_limits(self) -> Self:
        if self.lease_renew_seconds >= self.lease_seconds:
            raise ValueError("lease 갱신 주기는 만료 시간보다 짧아야 합니다")
        # 실행마다 1개 + lease 갱신 1개 + API 요청 최소 1개
        if self.db_pool_size < self.run_concurrency + 2:
            raise ValueError("DB 연결 풀은 동시 실행 수보다 2개 이상 커야 합니다")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
