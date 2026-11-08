"""SQL 검증 실패를 원래 설계 객체의 RULE-07 지적으로 바꾼다. 지문이 같은 문제는 하나로 합친다."""

from collections.abc import Mapping

from specton.contracts import DesignState, Finding, SqlValidation, StepStatus, ValidationStatus
from specton.contracts.findings import FindingSource, FindingTarget, Severity
from specton.review.fingerprint import fingerprint


def ddl_validation_findings(
    design: DesignState, result: SqlValidation, *, severities: Mapping[str, Severity]
) -> tuple[Finding, ...]:
    """SQL 결함만 지적으로 만든다. 환경 오류와 미검증은 기존 실행·사람 확인 경로가 처리한다."""
    if result.status is not ValidationStatus.FAILED:
        return ()
    severity = severities.get("RULE-07")
    if severity is None:
        raise ValueError("RULE-07 심각도가 정해지지 않았습니다 (rules.yaml)")
    model = design.normalized
    if model is None:
        raise ValueError("RULE-07 대상에 필요한 정리 결과가 없습니다")
    tables = sorted(model.tables, key=lambda table: table.id)
    fks = sorted(model.foreign_keys, key=lambda fk: fk.id)
    statements = [
        ("entity", table.entity_id)
        if table.entity_id is not None
        else ("relationship", table.relationship_id)
        for table in tables
    ] + [("relationship", fk.relationship_id) for fk in fks]
    known = {
        *(("entity", entity.id) for entity in design.entities),
        *(("relationship", rel.id) for rel in design.relationships),
    }
    # 지문이 같은 문제는 지적 하나로 합치고 근거는 모두 남긴다 (docs/04 「지적 확정 절차」).
    # RULE-07은 심각도가 하나이고 복귀 단계가 없어 합칠 것은 근거뿐이다.
    merged: dict[str, tuple[str, tuple[FindingTarget, ...], list[str]]] = {}
    for step in result.steps:
        if step.status is not StepStatus.FAILED:
            continue
        for issue in step.issues:
            if issue.statement_index is None:
                sources = sorted({source for source in statements if source[1] is not None})
            else:
                if issue.statement_index >= len(statements):
                    raise ValueError("SQL 오류의 문장 번호가 생성한 DDL 범위를 벗어납니다")
                sources = [statements[issue.statement_index]]
            if not sources or any(source not in known for source in sources):
                raise ValueError("SQL 오류의 원래 설계 대상을 찾을 수 없습니다")
            targets = tuple(FindingTarget(kind=kind, id=source_id) for kind, source_id in sources)
            kind = f"{step.name.value}:{issue.code}"
            quote = issue.message or f"SQL 검증 {step.name.value} 단계에서 {issue.code} 오류"
            if issue.statement_index is not None:
                # 합친 지적 안에서도 근거마다 어느 문장의 문제인지 구분되게 한다 (1부터 셈).
                quote = f"문장 {issue.statement_index + 1}: {quote}"
            key = fingerprint("RULE-07", kind, targets)
            merged.setdefault(key, (kind, targets, []))[2].append(quote)
    if not merged:
        raise ValueError("SQL 검증 실패에 문제 목록이 없습니다")
    return tuple(
        Finding(
            id=f"RULE-07-{design.iteration}-{number}",
            source=FindingSource.RULE,
            rule_code="RULE-07",
            kind=kind,
            severity=severity,
            targets=targets,
            evidence=tuple({"quote": quote} for quote in dict.fromkeys(quotes)),
            suggestion="생성한 SQL과 해당 설계 객체를 확인한다.",
            target_stage=None,
            fingerprint=key,
            iteration=design.iteration,
        )
        for number, (key, (kind, targets, quotes)) in enumerate(merged.items(), start=1)
    )
