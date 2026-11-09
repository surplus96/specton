"""최종 설계의 FR 연결과 CRUD 정합성 검사 (#15). 그래프 연결은 호출자가 담당한다."""

from collections.abc import Mapping

from specton.contracts import DesignState, Finding
from specton.contracts.base import Crud, RequirementType, TargetStage
from specton.contracts.findings import FindingSource, FindingTarget, Severity
from specton.review.fingerprint import fingerprint


def check_design_rules(
    design: DesignState,
    *,
    severities: Mapping[str, Severity],
    crud_exemption_reasons: Mapping[str, tuple[Crud | str, ...]],
) -> tuple[Finding, ...]:
    """RULE-02의 미연결 FR과 RULE-06만 검사한다. CRUD 네 종류를 강제하지 않는다.

    ID·참조·req_ids 유효성은 기존 정리 검사가 담당한다. 이 함수는 A03 검사를
    우회한 수정 설계에도 적용한다. 비기능 요구만 남은 미사용 엔티티는 A09가 판단한다.
    """
    findings: list[Finding] = []

    def add(
        code: str,
        kind: str,
        target: FindingTarget,
        quote: str,
        suggestion: str,
        stage: TargetStage | None,
    ) -> None:
        severity = severities.get(code)
        if severity is None:
            raise ValueError(f"{code}의 심각도가 정해지지 않았습니다 (rules.yaml)")
        targets = (target,)
        findings.append(
            Finding(
                id=f"{code}-{design.iteration}-{len(findings) + 1}",
                source=FindingSource.RULE,
                rule_code=code,
                kind=kind,
                severity=severity,
                targets=targets,
                evidence=({"quote": quote},),
                suggestion=suggestion,
                target_stage=stage,
                fingerprint=fingerprint(code, kind, targets),
                iteration=design.iteration,
            )
        )

    linked = {req for fn in design.functions for req in fn.req_ids}
    fr_ids = {req.id for req in design.requirements if req.type is RequirementType.FR}
    for req in design.requirements:
        if req.id in fr_ids and req.id not in linked:
            add(
                "RULE-02",
                "unlinked_fr",
                FindingTarget(kind="requirement", id=req.id),
                f"FR {req.id}를 근거로 연결한 기능이 없습니다.",
                "요구사항을 구현하는 기능을 연결한다.",
                TargetStage.FUNCTIONS,
            )

    for entity in design.entities:
        used = {
            op
            for fn in design.functions
            for item in fn.entity_ops
            if item.entity_id == entity.id
            for op in item.operations
        }
        target = FindingTarget(kind="entity", id=entity.id)
        if not used:
            stage = (
                TargetStage.DATA_MODEL
                if linked.intersection(entity.req_ids)
                else TargetStage.FUNCTIONS
                if fr_ids.intersection(entity.req_ids)
                else None
            )
            add(
                "RULE-06",
                "unused_entity",
                target,
                f"엔티티 {entity.id}에 조작을 연결한 기능이 없습니다.",
                "요구사항에 근거해 기능 연결 또는 엔티티 필요 여부를 확인한다.",
                stage,
            )
        invalid: list[str] = []
        for exemption in entity.crud_exemptions:
            allowed = crud_exemption_reasons.get(exemption.reason)
            if allowed is None:
                invalid.append(f"팩에 없는 면제 사유: {exemption.reason}")
            elif exemption.operation not in allowed:
                invalid.append(f"{exemption.reason}에서 면제하지 않는 조작: {exemption.operation}")
            if exemption.operation in used:
                invalid.append(f"면제한 조작을 기능이 사용: {exemption.operation}")
        if invalid:
            add(
                "RULE-06",
                "invalid_exemption",
                target,
                " / ".join(dict.fromkeys(invalid)),
                "팩의 면제 사유·조작과 실제 기능 조작이 일치하도록 수정한다.",
                TargetStage.DATA_MODEL,
            )
    return tuple(findings)
