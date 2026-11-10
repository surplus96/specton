"""팩의 처리 정책을 실제 지적에 적용한다. 동적 복귀는 검사기가 계산한 경로를 보존한다."""

from collections.abc import Mapping
from pathlib import Path

from specton.contracts import Finding
from specton.packs.loader import ComplianceCheck, RulePolicy, load_common


def load_policies(*, root: Path) -> dict[str, RulePolicy]:
    rules = load_common(root=root).rules
    return {**{r.id: r for r in rules.rules}, **{r.id: r for r in rules.standard_compliance.checks}}


def apply_policy(
    finding: Finding, policies: Mapping[str, RulePolicy], *, inferred_manual: bool = False
) -> tuple[Finding, bool]:
    policy = policies.get(finding.rule_code or "")
    if isinstance(policy, ComplianceCheck):
        policy = policy.subtypes.get(finding.kind.split(":", 1)[0], policy)
    if policy is None or policy.resolved_handling is None:
        return finding, inferred_manual  # 이전 draft 설정: 검사기가 계산한 경로 유지
    if policy.severity is None:
        raise ValueError(f"{finding.rule_code}: 처리 정책의 심각도가 없습니다")
    handling = policy.resolved_handling
    if inferred_manual and handling == "fixed":
        raise ValueError(f"{finding.rule_code}: 사람 조치 문제를 고정 재작업으로 보낼 수 없습니다")
    stage = finding.target_stage
    if handling == "fixed":
        stage = policy.target_stage
    elif handling in {"manual", "informational"}:
        stage = None
    updated = finding.evolve(target_stage=stage, severity=policy.severity)
    manual = handling == "manual" or (handling == "dynamic" and inferred_manual)
    return updated, manual
