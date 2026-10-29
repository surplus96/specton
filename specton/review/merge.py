"""리뷰 합류·근거 확인·지적 병합 (04 문서 "지적 확정 절차" 1~3단계, #18).

리뷰 가지(BranchResult)와 규칙 지적을 모아 재작업 판단(`rework.decide_rework`)에 넘길 지적을 만든다.
- 합류: 현재 revision의 결과만 받는다. 실패하거나 빠진 가지는 불완전 검토로 표시하고
  남은 결과로 진행한다.
- 근거 확인: LLM 지적의 대상 ID·근거 요구사항·인용이 현재 입력에 있는지 확인하고,
  없으면 제외해 기록한다. 규칙 지적은 코드가 현재 설계에서 만들므로 확인하지 않는다.
- 병합: 지문이 같은 지적만 합친다. 규칙 지적과 LLM 지적은 대상이 같아도 따로 남긴다.
"""

import logging
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from specton.contracts import BranchResult, DesignState, Finding
from specton.contracts.findings import Evidence, FindingSource, Severity
from specton.review.rework import earliest_stage

logger = logging.getLogger(__name__)

RejectReason = Literal["unknown_target", "unknown_req_id", "quote_not_found"]
SEVERITY_ORDER: tuple[Severity, ...] = (Severity.MINOR, Severity.MAJOR, Severity.CRITICAL)


@dataclass(frozen=True)
class RejectedFinding:
    """근거 확인에서 제외한 지적. 로그·HITL 2 화면에서 볼 수 있게 남긴다."""

    finding: Finding
    reason: RejectReason
    detail: str


@dataclass(frozen=True)
class ReviewMerge:
    findings: tuple[Finding, ...]  # 규칙 지적 먼저, 그다음 관점 순서의 LLM 지적
    rejected: tuple[RejectedFinding, ...] = ()
    failed_branches: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        """모든 리뷰 가지가 성공했는지. False면 불완전 검토로 표시한다 (TC-F14)."""
        return not self.failed_branches


def merge_review(
    state: DesignState,
    results: Sequence[BranchResult],
    expected: Sequence[str],
    *,
    rule_findings: Sequence[Finding] = (),
) -> ReviewMerge:
    """리뷰 가지 결과와 규칙 지적을 합쳐 재작업 판단에 넘길 지적을 만든다.

    expected는 실행해야 했던 리뷰 가지(관점 reviewer_id)다. 결과가 없는 가지는 실패로 본다.
    """
    joined = _join(state, results, expected)
    _check_rule_findings(rule_findings)
    failed = tuple(b for b in expected if b not in joined or not joined[b].ok)
    if failed:
        logger.warning("불완전 검토: 실패한 리뷰 가지 %s", ", ".join(failed))

    llm_findings = [f for b in expected if b in joined for f in joined[b].findings]
    targets = _known_targets(state)
    texts = {r.id: _normalize(r.text) for r in state.requirements}
    checked = [(f, _ground(f, targets, texts)) for f in llm_findings]
    rejected = tuple(RejectedFinding(f, *problem) for f, problem in checked if problem)
    for r in rejected:
        logger.warning("근거 확인 실패로 지적 %s 제외: %s %s", r.finding.id, r.reason, r.detail)

    accepted = [*rule_findings, *(f for f, problem in checked if problem is None)]
    return ReviewMerge(findings=_merge_same(accepted), rejected=rejected, failed_branches=failed)


def _join(
    state: DesignState, results: Sequence[BranchResult], expected: Collection[str]
) -> dict[str, BranchResult]:
    """같은 revision의 결과만 합류한다. 다른 revision은 이전 실행의 결과라 오류로 올린다."""
    for r in results:
        if r.revision != state.revision:
            raise ValueError(
                f"리뷰 가지 {r.branch}의 revision {r.revision}이 현재 {state.revision}과 다릅니다"
            )
        if r.branch not in expected:
            raise ValueError(f"설정에 없는 리뷰 가지입니다: {r.branch}")
    repeated = sorted(b for b, n in Counter(r.branch for r in results).items() if n > 1)
    if repeated:
        raise ValueError(f"리뷰 가지 결과가 두 번 들어왔습니다: {', '.join(repeated)}")
    return {r.branch: r for r in results}


def _check_rule_findings(findings: Sequence[Finding]) -> None:
    not_rule = [f.id for f in findings if f.source is not FindingSource.RULE]
    if not_rule:
        raise ValueError(f"rule_findings에 규칙 지적이 아닌 것이 있습니다: {', '.join(not_rule)}")


def _known_targets(state: DesignState) -> frozenset[str]:
    """현재 설계에 있는 대상. FindingTarget과 같은 `kind:id` 모양이다."""
    return frozenset(
        [
            *(f"requirement:{r.id}" for r in state.requirements),
            *(f"function:{f.id}" for f in state.functions),
            *(f"entity:{e.id}" for e in state.entities),
            *(f"attribute:{a.id}" for e in state.entities for a in e.attributes),
            *(f"relationship:{r.id}" for r in state.relationships),
        ]
    )


def _ground(
    finding: Finding, targets: frozenset[str], texts: Mapping[str, str]
) -> tuple[RejectReason, str] | None:
    """LLM 지적의 대상·근거가 현재 입력에 있는지. 문제가 있으면 첫 문제를 돌려준다."""
    if finding.source is FindingSource.RULE:
        return None
    for t in finding.targets:
        if f"{t.kind}:{t.id}" not in targets:
            return "unknown_target", f"{t.kind}:{t.id}"
    for e in finding.evidence:
        problem = _ground_evidence(e, texts)
        if problem:
            return problem
    return None


def _ground_evidence(e: Evidence, texts: Mapping[str, str]) -> tuple[RejectReason, str] | None:
    """인용이 근거 요구사항 문장에 그대로 있는지. req_id가 없으면 어느 요구사항이든 된다."""
    if e.req_id is not None and e.req_id not in texts:
        return "unknown_req_id", e.req_id
    pool = [texts[e.req_id]] if e.req_id is not None else texts.values()
    quote = _normalize(e.quote)
    if any(quote in text for text in pool):
        return None
    return "quote_not_found", f"{e.req_id}: {e.quote}" if e.req_id else e.quote


def _normalize(text: str) -> str:
    """줄바꿈·연속 공백 차이만 무시한다. 문구가 다르면 인용으로 보지 않는다."""
    return " ".join(text.split())


def _merge_same(findings: Sequence[Finding]) -> tuple[Finding, ...]:
    """지문이 같은 지적을 처음 나온 순서대로 하나로 합친다."""
    order = dict.fromkeys(f.fingerprint for f in findings)
    return tuple(_combine([f for f in findings if f.fingerprint == fp]) for fp in order)


def _combine(same: Sequence[Finding]) -> Finding:
    """첫 지적을 남기고 근거는 모두 보존한다. 심각도는 가장 높게, 복귀 단계는 가장 앞으로."""
    first = same[0]
    if len(same) == 1:
        return first
    stages = [f.target_stage for f in same if f.target_stage is not None]
    return first.evolve(
        severity=max((f.severity for f in same), key=SEVERITY_ORDER.index),
        target_stage=earliest_stage(stages) if stages else None,
        evidence=tuple(dict.fromkeys(e for f in same for e in f.evidence)),
    )
