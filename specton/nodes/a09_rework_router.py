"""A09 조건부 재작업 판단 (04 문서, REQ-16).

코드(`specton.review.rework`)가 target_stage를 정하지 못한 지적에 대해서만 부른다.
복귀 단계 3개 중 하나 또는 판단 불가를 돌려준다. 다른 노드와 달리 LLM 오류를
올리지 않고 "답 없음"으로 바꾼다: 재작업 판단 실패는 실행 실패가 아니라 HITL 2로 넘길 일이다.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from specton.config import Settings
from specton.contracts import DesignState, Finding
from specton.contracts.base import Contract, NonEmptyText, TargetStage
from specton.llm.client import LLMClient
from specton.llm.errors import LLMError
from specton.nodes.common import NodeRun, build_request
from specton.packs.examples import load_examples

logger = logging.getLogger(__name__)

PROMPT_VERSION = "a09-v1"
SYSTEM_PROMPT = """\
너는 설계 재작업 라우터다. 검토 지적을 고치려면 어느 단계부터 다시 만들어야 하는지 판단한다.
- requirements: 요구사항 해석·분할이 잘못됐거나 원문 확인이 필요하다 (요구사항 분석부터)
- functions: 기능 분해·묶음·요구사항 연결이 잘못됐다 (기능 설계부터)
- data_model: 엔티티·속성·관계·CRUD가 잘못됐다 (엔티티 설계부터)
- 지적들이 서로 다른 단계를 가리키면 가장 앞 단계를 고른다.
- 근거가 부족하거나 모호하면 undecidable을 고른다. 추측으로 단계를 고르지 않는다.
- rationale에는 판단 근거를 한두 문장으로 적는다."""


class A09Output(Contract):
    decision: Literal["requirements", "functions", "data_model", "undecidable"]
    rationale: NonEmptyText


@dataclass(frozen=True)
class RouterAnswer:
    """A09 답. stage가 None이면 판단 불가이거나 호출이 실패한 것이다 (HITL 2)."""

    stage: TargetStage | None
    rationale: str | None = None
    error_code: str | None = None  # 호출 실패 시 오류 코드 (화면 표시·기록용)


def run(
    client: LLMClient,
    state: DesignState,
    settings: Settings,
    *,
    pack: str,
    findings: Sequence[Finding],
    token_budget: int | None = None,
) -> NodeRun[RouterAnswer]:
    """target_stage가 없는 지적(`ReworkDecision.unrouted`)의 복귀 단계를 묻는다."""
    request = build_request(
        settings,
        role="review",
        stage="A09",
        prompt_version=PROMPT_VERSION,
        system=SYSTEM_PROMPT,
        data=_router_data(state, findings),
        examples=load_examples(pack, "A09", A09Output),
    )
    try:
        result = client.complete(request, A09Output, token_budget=token_budget)
    except LLMError as exc:
        logger.warning("A09 재작업 판단 실패: %s", exc.code)
        return NodeRun(output=RouterAnswer(stage=None, error_code=exc.code), calls=exc.calls)
    output = result.output
    stage = None if output.decision == "undecidable" else TargetStage(output.decision)
    return NodeRun(output=RouterAnswer(stage=stage, rationale=output.rationale), calls=result.calls)


def _router_data(state: DesignState, findings: Sequence[Finding]) -> dict[str, Any]:
    """지적과 그 근거 요구사항만 담는다. 전체 설계는 넣지 않는다."""
    req_ids = {e.req_id for f in findings for e in f.evidence if e.req_id is not None}
    return {
        "findings": [
            f.model_dump(
                mode="json", include={"id", "kind", "severity", "targets", "evidence", "suggestion"}
            )
            for f in findings
        ],
        "requirements": [
            r.model_dump(mode="json", include={"id", "text", "type"})
            for r in state.requirements
            if r.id in req_ids
        ],
    }
