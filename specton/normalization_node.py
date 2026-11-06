"""실제 모델 정리 → 그래프 상태 (#17). 문제 분류 정책은 #15 어댑터를 주입한다.

노드는 DB에 쓰지 않는다. 실행기가 DesignState.normalized를 기존 모델과 함께 저장·해시한다.
API의 create_graph가 #15의 실제 변환기를 연결한다. 실패를 빈 성공으로 대체하지 않는다.
"""

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypedDict

from specton.codegen.normalize_step import normalize_from_state
from specton.contracts import DesignState, Finding
from specton.contracts.findings import FindingSource, Severity
from specton.contracts.normalized import Normalized, Problem, ProblemCode
from specton.graph import GraphState, Node


class FailureReview(TypedDict):
    """#15의 실제 반환형을 R1 그래프에 맞추는 내부 콜백 결과. 체크포인트에는 저장하지 않는다."""

    findings: tuple[Finding, ...]
    requires_manual_review: bool


type FailureMapper = Callable[[DesignState, tuple[Problem, ...]], FailureReview]


def normalization_node(map_failure: FailureMapper, *, root: Path) -> Node:
    """정리 노드. `root`는 호출자가 settings.pack_root를 넘기며 명명 인자를 따로 주입하지 않는다.

    R4의 변환 함수 이름·반환 클래스에 의존하지 않고, 준비된 함수를 콜백으로 감싼다.
    Problem.code·decision·pending은 변환기에 그대로 전달한다 (특히 FK 충돌 D4/D13 구분).
    """

    def normalize(state: GraphState) -> Mapping[str, Any]:
        design = state["design"].evolve(normalized=None)
        result = normalize_from_state({"design": design}, root=root)
        if isinstance(result, Normalized):
            return {
                "design": design.evolve(normalized=result.model),
                "normalization_failed": False,
                "requires_manual_review": False,
                "rule_findings": (),
            }
        if not result.problems:
            raise ValueError("정리 실패에 문제 목록이 없습니다")
        for p in result.problems:
            if p.code in (ProblemCode.PACK_MISMATCH, ProblemCode.OUTPUT_TRACE):
                raise ValueError(f"정리 실행 오류: {p.code.value} ({p.target})")
        review = map_failure(design, result.problems)
        if type(review["requires_manual_review"]) is not bool:
            raise ValueError("requires_manual_review는 bool이어야 합니다")
        findings = review["findings"]
        if not any(
            f.source is FindingSource.RULE and f.severity is Severity.CRITICAL for f in findings
        ):
            raise ValueError("정리 실패에는 차단 규칙 지적이 필요합니다")
        return {
            "design": design,
            "normalization_failed": True,
            "rule_findings": findings,
            "requires_manual_review": review["requires_manual_review"],
        }

    return normalize
