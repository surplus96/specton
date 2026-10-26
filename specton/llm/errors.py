"""LLM 호출 실패 종류. 실패를 빈 성공 응답으로 바꾸지 않고 종류별 예외로 알린다."""

from collections.abc import Sequence

from specton.llm.types import CallRecord


class LLMError(Exception):
    """모든 LLM 호출 실패의 기반. 실패까지의 호출 기록(calls)을 함께 담는다."""

    def __init__(self, message: str, calls: Sequence[CallRecord] = ()) -> None:
        super().__init__(message)
        self.calls: tuple[CallRecord, ...] = tuple(calls)


class LLMRefusalError(LLMError):
    """모델이 응답을 거절했다. 같은 요청을 다시 보내지 않는다."""


class LLMTimeoutError(LLMError):
    """호출이 타임아웃(SPECTON_LLM_TIMEOUT_SECONDS)을 넘겼다."""


class LLMAPIError(LLMError):
    """인증·요청 형식 오류이거나, SDK 재시도 후에도 남은 API 오류."""


class LLMContractError(LLMError):
    """재요청을 다 쓴 뒤에도 출력이 계약(출력 모델)을 어겼다."""


class LLMBudgetExceededError(LLMError):
    """호출에 쓴 토큰이 남은 실행 예산을 넘었다."""
