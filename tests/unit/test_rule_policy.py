"""승인 팩의 의도적인 null, 지적 처리 경로·심각도·세부 유형 검증."""

import pytest
from pydantic import ValidationError

from specton.contracts import Finding
from specton.packs.build import DEFAULT_ROOT
from specton.packs.loader import ComplianceCheck, RulePolicy, load_common
from specton.review.rule_policy import apply_policy, load_policies


def finding(code="RULE-04", kind="unsupported_relationship:D4", stage=None):
    return Finding(
        id="policy-finding",
        source="rule",
        rule_code=code,
        kind=kind,
        severity="major",
        targets=({"kind": "entity", "id": "E1"},),
        evidence=({"quote": "코드 검사"},),
        suggestion="확인한다",
        target_stage=stage,
        fingerprint="policy",
        iteration=0,
    )


@pytest.mark.parametrize("handling", ["dynamic", "manual", "informational"])
def test_approved_common_accepts_intentional_nulls(handling):
    common = load_common()
    assert common.manifest.status == "approved"
    assert any(
        r.handling == handling
        for r in (*common.rules.rules, *common.rules.standard_compliance.checks)
    )


@pytest.mark.parametrize(
    "handling,stage,severity",
    [
        ("fixed", None, "major"),
        ("dynamic", "data_model", "major"),
        ("manual", "data_model", "major"),
        ("informational", None, "major"),
    ],
)
def test_inconsistent_policy_is_rejected(handling, stage, severity):
    with pytest.raises(ValidationError):
        RulePolicy(handling=handling, target_stage=stage, severity=severity)


@pytest.mark.parametrize("subtype", [False, True])
def test_sc_critical_is_rejected_even_inside_subtypes(subtype):
    config = dict(
        id="SC-04", name="forbidden", severity="major", target_stage=None, handling="manual"
    )
    if subtype:
        config["subtypes"] = {
            "synonym": dict(severity="critical", target_stage=None, handling="manual")
        }
    else:
        config["severity"] = "critical"
    with pytest.raises(ValidationError, match="critical"):
        ComplianceCheck.model_validate(config)


@pytest.mark.parametrize("manual,stage", [(True, None), (False, "data_model")])
def test_dynamic_rule04_preserves_manual_support_gap_and_design_rework(manual, stage):
    updated, needs_person = apply_policy(
        finding(stage=stage), load_policies(root=DEFAULT_ROOT), inferred_manual=manual
    )
    assert updated.target_stage == stage
    assert updated.severity == "critical"
    assert needs_person == manual


@pytest.mark.parametrize(
    "kind,severity,manual",
    [
        ("forbidden_word:금칙", "major", True),
        ("synonym:등록", "minor", False),
    ],
)
def test_sc04_subtype_selects_its_own_policy(kind, severity, manual):
    updated, needs_person = apply_policy(
        finding(code="SC-04", kind=kind, stage="data_model"), load_policies(root=DEFAULT_ROOT)
    )
    assert updated.severity == severity
    assert updated.target_stage is None
    assert needs_person == manual
