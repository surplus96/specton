"""공통 LLM client. 모든 노드는 이 client를 주입받아 LLM을 호출한다.

실제 전송(OpenAI, 테스트용 stub)은 Transport로 분리하고,
출력 검증·재요청·호출 기록은 여기서 한 번만 구현한다.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ValidationError

from specton.llm.errors import (
    LLMAPIError,
    LLMBudgetExceededError,
    LLMContractError,
    LLMRefusalError,
    LLMTimeoutError,
)
from specton.llm.types import CallOutcome, CallRecord, LLMRequest, LLMResult, Message

Clock = Callable[[], float]


@dataclass(frozen=True)
class RawReply:
    """Transport가 돌려주는 검증 전 응답."""

    text: str | None
    refusal: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class Transport(Protocol):
    def send(self, request: LLMRequest, output_model: type[BaseModel]) -> RawReply:
        """요청을 보내고 검증 전 응답을 돌려준다. 실패는 LLMTimeoutError·LLMAPIError로 알린다."""
        ...


class LLMClient:
    def __init__(
        self, transport: Transport, *, max_structured_retries: int, clock: Clock = time.monotonic
    ) -> None:
        if max_structured_retries < 0:
            raise ValueError("max_structured_retries는 0 이상이어야 한다")
        self._transport = transport
        self._max_retries = max_structured_retries
        self._clock = clock

    def complete[OutputT: BaseModel](
        self,
        request: LLMRequest,
        output_model: type[OutputT],
        *,
        token_budget: int | None = None,
    ) -> LLMResult[OutputT]:
        """출력 모델로 검증된 결과를 돌려준다.

        형식이 틀리면 오류 내용을 담아 최대 max_structured_retries번 다시 요청한다.
        token_budget을 주면 재요청 전에 지금까지 쓴 토큰이 예산 안인지 확인한다.
        """
        calls: tuple[CallRecord, ...] = ()
        current = request
        problems = ""
        for attempt in range(1, self._max_retries + 2):
            if attempt > 1 and token_budget is not None and _spent(calls) >= token_budget:
                raise LLMBudgetExceededError(f"토큰 예산 {token_budget} 소진", calls)
            reply, duration_ms = self._send(current, output_model, attempt, calls)
            if reply.refusal is not None:
                calls = (*calls, _record(current, attempt, "refused", reply, duration_ms))
                raise LLMRefusalError(f"{request.stage}: 모델이 응답을 거절함", calls)
            try:
                output = output_model.model_validate_json(reply.text or "")
            except ValidationError as exc:
                calls = (*calls, _record(current, attempt, "invalid_output", reply, duration_ms))
                problems = _summarize(exc)
                current = _with_retry_prompt(current, reply.text or "", problems)
                continue
            calls = (*calls, _record(current, attempt, "ok", reply, duration_ms))
            return LLMResult[OutputT](output=output, calls=calls)
        raise LLMContractError(f"{request.stage}: 재요청 후에도 출력 형식 위반 — {problems}", calls)

    def _send(
        self,
        request: LLMRequest,
        output_model: type[BaseModel],
        attempt: int,
        calls: tuple[CallRecord, ...],
    ) -> tuple[RawReply, int]:
        started = self._clock()
        try:
            reply = self._transport.send(request, output_model)
        except (LLMTimeoutError, LLMAPIError) as exc:
            outcome: CallOutcome = "timeout" if isinstance(exc, LLMTimeoutError) else "api_error"
            failed = _record(request, attempt, outcome, None, _elapsed_ms(started, self._clock()))
            raise type(exc)(str(exc), (*calls, failed)) from exc
        return reply, _elapsed_ms(started, self._clock())


def _record(
    request: LLMRequest,
    attempt: int,
    outcome: CallOutcome,
    reply: RawReply | None,
    duration_ms: int,
) -> CallRecord:
    return CallRecord(
        stage=request.stage,
        prompt_version=request.prompt_version,
        model=request.model,
        attempt=attempt,
        outcome=outcome,
        input_tokens=reply.input_tokens if reply else 0,
        output_tokens=reply.output_tokens if reply else 0,
        duration_ms=duration_ms,
    )


def _elapsed_ms(started: float, ended: float) -> int:
    return max(0, round((ended - started) * 1000))


def _spent(calls: tuple[CallRecord, ...]) -> int:
    return sum(c.input_tokens + c.output_tokens for c in calls)


def _summarize(exc: ValidationError) -> str:
    """검증 오류 요약. 입력값은 넣지 않는다(원문이 로그·프롬프트로 새지 않게)."""
    errors = exc.errors(include_input=False, include_url=False)
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in errors
    )


def _with_retry_prompt(request: LLMRequest, bad_text: str, problems: str) -> LLMRequest:
    retry = Message(
        role="user",
        content=f"직전 응답이 출력 스키마를 어겼다: {problems}. 같은 스키마로 다시 답하라.",
    )
    previous = Message(role="assistant", content=bad_text)
    return request.model_copy(update={"messages": (*request.messages, previous, retry)})
