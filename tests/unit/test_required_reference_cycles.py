"""실행 동작을 막는 필수 순환과 정상 선택/N:M 관계를 구분한다."""

import pytest
from test_normalize import PACK, RECEIPT, WAREHOUSE, _design, _rel

from specton.codegen.normalize import _required_reference_cycles
from specton.contracts import Severity
from specton.review.normalization_findings import map_normalization_failure


def test_two_way_mandatory_reference_routes_all_relationships_to_design():
    relations = [_rel("REL-01", "ENT-wh", "ENT-rc"), _rel("REL-02", "ENT-rc", "ENT-wh")]
    problems = tuple(_required_reference_cycles(relations))
    assert len(problems) == 1
    assert problems[0].target == "REL-01,REL-02"
    design = _design([WAREHOUSE, RECEIPT], relations).evolve(
        versions={"pack_id": PACK.name, "pack_version": PACK.version}
    )
    result = map_normalization_failure(design, problems, severities={"RULE-04": Severity.CRITICAL})
    (finding,) = result["findings"]
    assert finding.target_stage == "data_model"
    assert {t.id for t in finding.targets} == {"REL-01", "REL-02"}
    assert not result["requires_manual_review"]


@pytest.mark.parametrize("change", [{"optional": True}, {"cardinality": "N:M"}])
def test_optional_edge_or_junction_does_not_create_mandatory_cycle(change):
    relations = [
        _rel("REL-01", "ENT-wh", "ENT-rc"),
        _rel("REL-02", "ENT-rc", "ENT-wh").evolve(**change),
    ]
    assert not tuple(_required_reference_cycles(relations))


def test_three_node_cycle_does_not_include_downstream_branch():
    relations = [
        _rel("REL-01", "ENT-a", "ENT-b"),
        _rel("REL-02", "ENT-b", "ENT-c"),
        _rel("REL-03", "ENT-c", "ENT-a"),
        _rel("REL-04", "ENT-c", "ENT-d"),
    ]
    (problem,) = _required_reference_cycles(relations)
    assert problem.target == "REL-01,REL-02,REL-03"
