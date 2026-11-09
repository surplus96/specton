"""#225 최종 설계 검사를 API 그래프에 연결한다. DB 저장·재작업 판단은 기존 경로를 쓴다."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from specton.graph import GraphState, Node
from specton.packs.loader import load_common
from specton.review.design_rules import check_design_rules
from specton.review.normalization_findings import rule_severities


def design_rules_node(*, root: Path) -> Node:
    """설정된 팩의 RULE-02·06 심각도·CRUD 면제 사유로 검사한다. SC는 후속 인계 범위다."""
    severities = rule_severities(root=root)
    exemptions = load_common(root=root).rules.crud_exemption_reasons

    def check(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        if state.get("normalization_failed") or design.normalized is None:
            raise ValueError("규칙 검사: 성공한 정리 결과가 없습니다")
        findings = check_design_rules(
            design, severities=severities, crud_exemption_reasons=exemptions
        )
        # 기존 SQL·정리 지적을 덮어쓰지 않는다. 최종 지문 중복 병합은 merge_review가 맡는다.
        return {"rule_findings": (*state.get("rule_findings", ()), *findings)}

    return check
