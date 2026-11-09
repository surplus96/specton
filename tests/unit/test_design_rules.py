"""A03를 우회한 최종 설계의 RULE-02·06 회귀 시험."""

import pytest

from specton.contracts import DesignState, Entity, Function, Requirement
from specton.contracts.design import Attribute, CrudExemption, EntityOp
from specton.packs.loader import load_common
from specton.review.design_rules import check_design_rules
from specton.review.normalization_findings import rule_severities


def design(*, used=(), exemptions=(), linked=True, nfr=False):
    req = Requirement(
        id="REQ-01",
        source_ref={"file_format": "csv", "row": 2},
        text="창고 조회",
        draft_text="창고 조회",
        type="NFR" if nfr else "FR",
        nfr_category="other" if nfr else None,
        analysis_version=1,
    )
    entity = Entity(
        id="ENT-1",
        pack="inventory",
        name="창고",
        description="창고",
        req_ids=(req.id,),
        crud_exemptions=tuple(
            CrudExemption(operation=op, reason=reason) for op, reason in exemptions
        ),
        attributes=(
            Attribute(
                id="ATTR-1", name="창고코드", data_type="varchar", length=10, req_ids=(req.id,)
            ),
        ),
    )
    fn = Function(
        id="FUNC-01",
        name="조회",
        description="조회",
        req_ids=(req.id if linked else "REQ-02",),
        entity_ops=(EntityOp(entity_id=entity.id, operations=used),) if used else (),
    )
    return DesignState(
        run_id="test-rules", requirements=(req,), entities=(entity,), functions=(fn,)
    )


def check(state):
    return check_design_rules(
        state,
        severities=rule_severities(),
        crud_exemption_reasons=load_common().rules.crud_exemption_reasons,
    )


@pytest.mark.parametrize(
    "linked,nfr,stage",
    [
        (True, False, "data_model"),
        (False, False, "functions"),
        (False, True, None),
        (True, True, "data_model"),
    ],
)
def test_unused_entity_routes_by_requirement_links(linked, nfr, stage):
    findings = check(design(linked=linked, nfr=nfr))
    unused = next(f for f in findings if f.kind == "unused_entity")
    assert unused.target_stage == stage
    assert unused.targets[0].id == "ENT-1"
    assert unused.severity == "critical"
    assert any(f.kind == "unlinked_fr" for f in findings) == (not linked and not nfr)


@pytest.mark.parametrize(
    "exemptions,used",
    [
        ((("D", "unknown"),), ("R",)),
        ((("U", "soft_delete"),), ("R",)),
        ((("D", "soft_delete"),), ("D",)),
    ],
)
def test_invalid_exemptions_are_data_model_findings(exemptions, used):
    findings = check(design(used=used, exemptions=exemptions))
    assert len(findings) == 1
    assert findings[0].kind == "invalid_exemption"
    assert findings[0].target_stage == "data_model"


@pytest.mark.parametrize(
    "exemptions",
    [(), (("D", "soft_delete"),), (("U", "immutable_ledger"), ("D", "immutable_ledger"))],
)
def test_read_only_entity_does_not_require_four_crud_operations(exemptions):
    assert check(design(used=("R",), exemptions=exemptions)) == ()


def test_fingerprint_is_stable_across_iterations():
    state = design()
    first = check(state)
    second = check(state.model_copy(update={"iteration": 2}))
    assert first[0].fingerprint == second[0].fingerprint
    assert first[0].id != second[0].id


def test_missing_severity_is_not_silently_ignored():
    with pytest.raises(ValueError, match="RULE-06"):
        check_design_rules(design(), severities={}, crud_exemption_reasons={})
