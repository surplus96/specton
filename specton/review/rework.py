"""재작업 판단 (03·04 문서, REQ-16, ADR-0010). LLM을 쓰지 않는 순수 함수다.

지적의 target_stage로 복귀 단계를 정하고, 정하지 못한 지적이 있을 때만 A09에 묻는다.
상한 도달·반복 지적·A09 판단 불가는 자동 루프를 멈추고 HITL 2로 넘긴다.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from specton.contracts import Finding
from specton.contracts.base import TargetStage
from specton.contracts.findings import Severity

# ADR-0010: 자동 재작업은 critical·major만. minor는 HITL 2의 참고 의견이다.
AUTO_REWORK_SEVERITIES = frozenset({Severity.CRITICAL, Severity.MAJOR})
# 앞 단계일수록 다시 실행하는 범위가 넓다. 여러 단계가 섞이면 가장 앞 단계로 묶는다.
STAGE_ORDER: tuple[TargetStage, ...] = (
    TargetStage.REQUIREMENTS,
    TargetStage.FUNCTIONS,
    TargetStage.DATA_MODEL,
)


class ReworkAction(StrEnum):
    NONE = "none"  # 자동 재작업할 지적 없음. HITL 2로 진행
    REWORK = "rework"  # target_stage부터 다시 실행
    ASK_ROUTER = "ask_router"  # target_stage가 없는 지적이 있어 A09에 묻는다
    HITL = "hitl"  # 자동 루프 중단, 사람에게 넘김


class HitlReason(StrEnum):
    LIMIT = "rework_limit"
    REPEATED = "repeated_findings"
    UNDECIDED = "router_undecided"


@dataclass(frozen=True)
class ReworkDecision:
    action: ReworkAction
    target_stage: TargetStage | None = None  # REWORK의 복귀 단계, ASK_ROUTER면 이미 정해진 단계
    hitl_reason: HitlReason | None = None
    unrouted: tuple[Finding, ...] = ()  # ASK_ROUTER일 때 A09에 넘길 지적


def decide_rework(
    findings: Sequence[Finding],
    *,
    rework_count: int,
    max_rework: int,
    previous_fingerprints: frozenset[str],
) -> ReworkDecision:
    """이번 반복의 지적으로 다음 행동을 정한다. rework_count는 지금까지 재작업한 횟수다."""
    actionable = [f for f in findings if f.severity in AUTO_REWORK_SEVERITIES]
    if not actionable:
        return ReworkDecision(ReworkAction.NONE)
    if rework_count >= max_rework:
        return ReworkDecision(ReworkAction.HITL, hitl_reason=HitlReason.LIMIT)
    if any(f.fingerprint in previous_fingerprints for f in actionable):
        return ReworkDecision(ReworkAction.HITL, hitl_reason=HitlReason.REPEATED)
    known = [f.target_stage for f in actionable if f.target_stage is not None]
    unrouted = tuple(f for f in actionable if f.target_stage is None)
    stage = earliest_stage(known) if known else None
    if unrouted:
        return ReworkDecision(ReworkAction.ASK_ROUTER, target_stage=stage, unrouted=unrouted)
    return ReworkDecision(ReworkAction.REWORK, target_stage=stage)


def resolve_with_router(
    decision: ReworkDecision, router_stage: TargetStage | None
) -> ReworkDecision:
    """A09 답으로 ASK_ROUTER를 마무리한다. 답이 없으면(판단 불가·호출 실패) HITL 2."""
    if decision.action is not ReworkAction.ASK_ROUTER:
        raise ValueError("A09 답은 ASK_ROUTER 결정에만 적용한다")
    if router_stage is None:
        return ReworkDecision(ReworkAction.HITL, hitl_reason=HitlReason.UNDECIDED)
    stages = [s for s in (decision.target_stage, router_stage) if s is not None]
    return ReworkDecision(ReworkAction.REWORK, target_stage=earliest_stage(stages))


def earliest_stage(stages: Iterable[TargetStage]) -> TargetStage:
    return min(stages, key=STAGE_ORDER.index)
