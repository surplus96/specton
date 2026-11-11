"""최종 설계의 RULE·SC를 API 그래프에 연결한다. DB 저장·재작업 판단은 기존 경로를 쓴다."""

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from specton.contracts import DesignState, Finding
from specton.graph import GraphState, Node
from specton.packs.build import pack_content_hash
from specton.packs.loader import Word, load_common
from specton.packs.provenance import policy_digest
from specton.review.design_rules import check_design_rules
from specton.review.normalization_findings import rule_severities, technical_name_findings
from specton.review.rule_policy import apply_policy, load_policies
from specton.review.standard_compliance import (
    OfficialStandard,
    Profile,
    check_standard_compliance,
    compliance_severities,
    load_official_standard,
    pack_words,
)


def design_rules_node(
    *,
    root: Path,
    expected_policy_digest: str | None = None,
    additional_words: Sequence[Word] = (),
) -> Node:
    """같은 root의 심각도·처리 정책·선별 적용을 사용한다. 기본 팩으로 우회하지 않는다."""
    severities = rule_severities(root=root)
    common = load_common(root=root)
    policies = load_policies(root=root)
    common_digest = pack_content_hash(root / "common")

    def official() -> OfficialStandard:
        return load_official_standard(root=root)

    def check(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        if state.get("normalization_failed") or design.normalized is None:
            raise ValueError("규칙 검사: 성공한 정리 결과가 없습니다")
        if common_digest != pack_content_hash(root / "common"):
            raise ValueError("규칙 검사: 공통 정책이 바뀌었습니다. 실행기를 재시작해야 합니다")
        recorded = design.normalized.policy_digest
        expected = (
            expected_policy_digest
            if expected_policy_digest is not None
            else policy_digest(root, design.normalized.pack)
        )
        if recorded is not None and recorded != expected:
            raise ValueError("규칙 검사: 정리 후 팩·표준 원본이 바뀌었습니다. 새 실행이 필요합니다")
        routed = [
            apply_policy(f, policies)
            for f in check_design_rules(
                design,
                severities=severities,
                crud_exemption_reasons=common.rules.crud_exemption_reasons,
            )
        ]
        compliance, manual = _compliance(
            design, root, common.naming.type_profile, official, additional_words
        )
        naming_routed = [apply_policy(f, policies) for f in technical_name_findings(design)]
        naming = tuple(f for f, _ in naming_routed)
        named_targets = {t.id for f in naming for t in f.targets}
        # 같은 미등록 사실은 기술 식별자 안내에서 한 번만 표시한다. 다른 SC 진단은 보존한다.
        compliance = tuple(
            f
            for f in compliance
            if not (
                f.rule_code == "SC-01"
                and f.severity == "minor"
                and f.target_stage is None
                and all(t.id in named_targets for t in f.targets)
            )
        )
        findings: tuple[Finding, ...] = (
            *naming,
            *state.get("rule_findings", ()),
            *(f for f, _ in routed),
            *compliance,
        )
        return {
            "rule_findings": findings,
            "requires_manual_review": (
                state.get("requires_manual_review", False)
                or manual
                or any(m for _, m in (*routed, *naming_routed))
            ),
        }

    return check


def _compliance(
    design: DesignState,
    root: Path,
    profile: Profile,
    official: Callable[[], OfficialStandard],
    additional_words: Sequence[Word] = (),
) -> tuple[tuple[Finding, ...], bool]:
    assert design.normalized is not None
    if not any(
        c.domain is None and c.attribute_id is not None
        for t in design.normalized.tables
        for c in t.columns
    ):
        return (), False
    result = check_standard_compliance(
        design,
        official=official(),
        words=(*pack_words(design.normalized.pack, root=root), *additional_words),
        severities=compliance_severities(root=root),
        profile=profile,
        root=root,
    )
    return result["findings"], result["requires_manual_review"]
