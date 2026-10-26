"""LLM 호출의 요청·결과 모델. 모두 불변(frozen)이다."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from specton.config import ReasoningEffort

Role = Literal["system", "user", "assistant"]
CallOutcome = Literal["ok", "invalid_output", "refused", "timeout", "api_error"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Message(_Frozen):
    role: Role
    content: str


class LLMRequest(_Frozen):
    """노드가 만드는 호출 요청. ID·SQL 같은 코드 책임은 여기에 넣지 않는다."""

    stage: str = Field(min_length=1)  # 예: "A01"
    prompt_version: str = Field(min_length=1)  # 예: "a01-v1"
    model: str = Field(min_length=1)
    messages: tuple[Message, ...] = Field(min_length=1)
    max_output_tokens: int = Field(gt=0)
    reasoning_effort: ReasoningEffort | None = None


class CallRecord(_Frozen):
    """API 호출 1회의 기록. 원문·키는 담지 않는다."""

    stage: str
    prompt_version: str
    model: str
    attempt: int = Field(ge=1)  # 1 = 최초 호출, 2 이상 = 재요청
    outcome: CallOutcome
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    duration_ms: int = Field(ge=0)


class LLMResult[OutputT: BaseModel](_Frozen):
    """검증을 통과한 출력과 그 출력을 얻기까지의 호출 기록."""

    output: OutputT
    calls: tuple[CallRecord, ...]

    @property
    def total_tokens(self) -> int:
        return sum(c.input_tokens + c.output_tokens for c in self.calls)
