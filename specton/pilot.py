"""#49 수동 시범 실행: 실제 설계 노드 A01~A04와 검토를 호출하고 사용량만 돌려준다.

client·설정·합성 입력은 호출자가 주입한다. DB·파일 저장과 실제 client 생성은 하지 않는다.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter

from pydantic import BaseModel

from specton.agent_nodes import design_nodes
from specton.codegen.model import Normalized
from specton.codegen.normalize_step import normalize_design
from specton.config import Settings
from specton.contracts import BranchResult, DesignState
from specton.graph import GraphState, initial_state
from specton.llm.client import LLMClient
from specton.llm.errors import LLMBudgetExceededError, LLMError, LLMTimeoutError
from specton.llm.types import CallRecord, LLMRequest, LLMResult
from specton.review.perspective import load_perspectives
from specton.review.reviewer import run_review


@dataclass(frozen=True)
class PilotResult:
    """검증된 설계와 호출 기록. 실패한 경우 앞 단계의 기록도 유지한다."""

    design: DesignState
    calls: tuple[CallRecord, ...]
    branches: tuple[BranchResult, ...] = ()
    error_code: str | None = None
    wall_time_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.error_code is None and bool(self.branches) and all(b.ok for b in self.branches)

    def usage(self, *, rates: Mapping[str, tuple[float, float]] | None = None) -> dict[str, object]:
        """원문·프롬프트·키 없이 출력할 기록. attempt는 구조화 출력 시도 번호다."""
        return {
            "run_id": self.design.run_id,
            "ok": self.ok,
            "error_code": self.error_code,
            "calls": [c.model_dump(mode="json") for c in self.calls],
            "input_tokens": sum(c.input_tokens for c in self.calls),
            "output_tokens": sum(c.output_tokens for c in self.calls),
            "call_duration_ms": sum(c.duration_ms for c in self.calls),
            "wall_time_ms": self.wall_time_ms,
            "structured_retries": sum(c.attempt > 1 for c in self.calls),
            "sdk_retry_count": None,  # 현재 client는 SDK 내부 재시도 횟수를 공개하지 않는다
            "schema_descriptions_in_input_tokens": True,  # #105 설명을 포함한 현행 스키마
            "estimated_cost_usd": _estimate_cost(self.calls, rates),
            "cost_basis": "reported_usage_at_uncached_standard_rates; excludes cache write charges",
        }


def _estimate_cost(
    calls: tuple[CallRecord, ...], rates: Mapping[str, tuple[float, float]] | None
) -> float | None:
    """100만 토큰당 단가를 호출자가 준다. 단가·실패 사용량이 없으면 비용을 지어내지 않는다."""
    if (
        not calls
        or rates is None
        or any(c.model not in rates or c.outcome in {"api_error", "timeout"} for c in calls)
    ):
        return None
    return (
        sum(c.input_tokens * rates[c.model][0] + c.output_tokens * rates[c.model][1] for c in calls)
        / 1_000_000
    )


class _RecordedClient(LLMClient):
    """공통 client의 결과를 모은다. 노드가 실패해도 그때까지의 호출 기록을 유지한다."""

    def __init__(self, client: LLMClient, token_limit: int, deadline: float) -> None:
        self._deadline = deadline
        self._client = client
        self._token_limit = token_limit
        self.calls: tuple[CallRecord, ...] = ()

    def complete[OutputT: BaseModel](
        self,
        request: LLMRequest,
        output_model: type[OutputT],
        *,
        token_budget: int | None = None,
    ) -> LLMResult[OutputT]:
        if perf_counter() >= self._deadline:
            raise LLMTimeoutError("시범 실행의 시간 한도를 넘었습니다")
        remaining = self._token_limit - sum(c.input_tokens + c.output_tokens for c in self.calls)
        if remaining <= 0:
            raise LLMBudgetExceededError("시범 실행의 토큰 예산을 다 썼습니다")
        budget = min(remaining, token_budget) if token_budget is not None else remaining
        try:
            result = self._client.complete(request, output_model, token_budget=budget)
        except LLMError as exc:
            self.calls = (*self.calls, *exc.calls)
            raise
        self.calls = (*self.calls, *result.calls)
        return result


def run_pilot(client: LLMClient, settings: Settings, design: DesignState) -> PilotResult:
    """시범 1회. 합성 원문 → A01~A04 → combined 검토. HITL·재작업은 없다."""
    if settings.review_mode != "combined":
        raise ValueError("시범 실행은 combined만 지원합니다. 병렬 비교는 그래프에서 실행합니다")
    started = perf_counter()
    recorded = _RecordedClient(
        client, settings.max_tokens_per_run, started + settings.run_timeout_seconds
    )
    nodes = design_nodes(lambda: recorded, settings)
    state = initial_state(design)
    try:
        for name in ("a01", "a02", "a03", "a04"):
            update = nodes[name](state)
            state = GraphState(
                design=update["design"],
                tokens_used=state.get("tokens_used", 0) + update["tokens_used"],
            )
        normalized = normalize_design(state["design"], root=settings.pack_root)
        if not isinstance(normalized, Normalized):
            return PilotResult(
                design=state["design"],
                calls=recorded.calls,
                error_code="NORMALIZATION_FAILED",
                wall_time_ms=int((perf_counter() - started) * 1000),
            )
        state["design"] = state["design"].evolve(normalized=normalized.model)
        review = run_review(
            recorded,
            load_perspectives(),
            state["design"],
            settings,
            pack=design.versions.pack_id,
        )
    except LLMError as exc:
        return PilotResult(
            design=state["design"],
            calls=recorded.calls,
            error_code=exc.code,
            wall_time_ms=int((perf_counter() - started) * 1000),
        )
    failed = next((b.error_code for b in review.results if not b.ok), None)
    return PilotResult(
        design=state["design"],
        calls=recorded.calls,
        branches=review.results,
        error_code=failed,
        wall_time_ms=int((perf_counter() - started) * 1000),
    )
