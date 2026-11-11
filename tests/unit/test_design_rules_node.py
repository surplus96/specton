"""실제 팩 설정·기존 규칙 지적을 사용하는 R1 규칙 노드."""

import shutil
from pathlib import Path

import pytest
import yaml

from specton.codegen.normalize_step import normalize_from_state
from specton.contracts import DesignState, Finding, VersionInfo
from specton.contracts.normalized import Normalized
from specton.design_rules_node import design_rules_node
from specton.graph import GraphState, initial_state
from specton.packs.build import DEFAULT_ROOT, read_yaml


def state(*, used: bool = False, exemptions: tuple = (), root: Path = DEFAULT_ROOT) -> GraphState:
    design = DesignState.model_validate({
        "run_id": "rules-node", "versions": VersionInfo(
            pack_id="inventory",
            pack_version=read_yaml(DEFAULT_ROOT / "inventory/manifest.yaml")["version"],
        ),
        "requirements": [{
            "id": "REQ-01", "source_ref": {"file_format": "csv", "row": 2},
            "text": "창고를 조회한다", "draft_text": "창고를 조회한다",
            "type": "FR", "analysis_version": 1,
        }],
        "functions": [{
            "id": "FUNC-01", "name": "창고 조회", "description": "창고 조회", "req_ids": ["REQ-01"],
            "entity_ops": [{"entity_id": "ENT-01", "operations": ["R"]}] if used else [],
        }],
        "entities": [{
            "id": "ENT-01", "pack": "inventory", "name": "창고", "description": "창고",
            "req_ids": ["REQ-01"], "crud_exemptions": exemptions,
            "attributes": [{
                "id": "ATTR-01", "name": "창고코드", "data_type": "varchar", "length": 10,
                "is_key": True, "nullable": False, "req_ids": ["REQ-01"],
            }],
        }],
    })  # fmt: skip
    result = normalize_from_state({"design": design}, root=root)
    assert isinstance(result, Normalized)
    return initial_state(design.evolve(normalized=result.model))


@pytest.mark.parametrize("rule", ["RULE-03", "RULE-07"])
def test_existing_normalization_and_sql_findings_are_preserved(rule: str) -> None:
    original = Finding(
        id=f"{rule}-old", source="rule", rule_code=rule, kind="existing", severity="critical",
        targets=({"kind": "entity", "id": "ENT-01"},), evidence=({"quote": "기존 검사 결과"},),
        suggestion="기존 문제를 확인한다", fingerprint=f"existing-{rule}", iteration=1,
    )  # fmt: skip
    graph = state()
    graph["rule_findings"] = (original,)
    findings = design_rules_node(root=DEFAULT_ROOT)(graph)["rule_findings"]
    assert findings[0] == original
    assert [(f.rule_code, f.kind) for f in findings[1:]] == [("RULE-06", "unused_entity")]


def test_custom_pack_severity_and_crud_exemptions_are_used(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    shutil.copytree(DEFAULT_ROOT, root)
    path = root / "common/rules.yaml"
    rules = read_yaml(path)
    for item in rules["rules"]:
        if item["id"] == "RULE-06":
            item["severity"] = "minor"
    rules["crud_exemption_reasons"]["local_readonly"] = ["D"]
    path.write_text(yaml.safe_dump(rules, allow_unicode=True), encoding="utf-8")
    node = design_rules_node(root=root)
    assert node(state(root=root))["rule_findings"][0].severity == "minor"
    assert (
        node(
            state(
                used=True, exemptions=({"operation": "D", "reason": "local_readonly"},), root=root
            )
        )["rule_findings"]
        == ()
    )


def test_missing_severity_does_not_fall_back_to_default_pack(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    shutil.copytree(DEFAULT_ROOT, root)
    path = root / "common/rules.yaml"
    rules = read_yaml(path)
    for item in rules["rules"]:
        if item["id"] == "RULE-06":
            item["severity"] = None
    path.write_text(yaml.safe_dump(rules, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match=r"RULE-06\.severity"):
        design_rules_node(root=root)(state())


def test_failed_normalization_is_not_treated_as_a_final_design() -> None:
    graph = state()
    graph["normalization_failed"] = True
    with pytest.raises(ValueError, match="정리"):
        design_rules_node(root=DEFAULT_ROOT)(graph)


@pytest.mark.parametrize(
    "name,type_,length,code,manual,stage",
    [
        ("창고", "varchar", 10, "SC-02", False, None),
        ("창고수", "varchar", 10, "SC-03", False, "data_model"),
        ("수작업여부", "char", 1, "SC-05", True, None),
    ],
)
def test_real_sc_policy_is_connected_to_final_rules(name, type_, length, code, manual, stage):
    graph = state(used=True)
    design = graph["design"]
    entity = design.entities[0]
    attr = entity.attributes[0].evolve(
        id="ATTR-02",
        name=name,
        data_type=type_,
        length=length,
        is_key=False,
    )
    design = design.evolve(entities=(entity.evolve(attributes=(*entity.attributes, attr)),))
    normalized = normalize_from_state({"design": design})
    assert isinstance(normalized, Normalized)
    if code == "SC-05":
        # 전체 공식 사전이면 이 이름도 올바르게 정리된다. 실제 표준명 충돌을 따로 만든다.
        table = normalized.model.tables[0]
        columns = tuple(
            c.evolve(physical_name="non_standard_name") if c.attribute_id == attr.id else c
            for c in table.columns
        )
        normalized = normalized.evolve(
            model=normalized.model.evolve(tables=(table.evolve(columns=columns),))
        )
    graph["design"] = design.evolve(normalized=normalized.model)
    result = design_rules_node(root=DEFAULT_ROOT)(graph)
    assert [(f.rule_code, f.target_stage) for f in result["rule_findings"]] == [(code, stage)]
    assert result["requires_manual_review"] is manual


def test_policy_drift_after_normalization_requires_new_run(tmp_path):
    root = tmp_path / "packs"
    shutil.copytree(DEFAULT_ROOT, root)
    graph = state(used=True, root=root)
    path = root / "common/rules.yaml"
    path.write_text(path.read_text() + "\n# 정책 파일 변경\n")
    with pytest.raises(ValueError, match="새 실행"):
        design_rules_node(root=root)(graph)


def test_exploration_words_are_registered_only_in_the_injected_condition() -> None:
    from specton.packs.loader import Word

    graph = state(used=True)
    design = graph["design"]
    entity = design.entities[0]
    attr = entity.attributes[0].evolve(name="쩨큐시험어코드")
    assert design.normalized is not None
    table = design.normalized.tables[0]
    column = table.columns[0].evolve(name=attr.name, physical_name="zzq_cd", domain=None)
    graph["design"] = design.evolve(
        entities=(entity.evolve(attributes=(attr,)),),
        normalized=design.normalized.evolve(tables=(table.evolve(columns=(column,)),)),
    )
    before = design_rules_node(root=DEFAULT_ROOT)(graph)["rule_findings"]
    assert any(f.rule_code == "SC-01" for f in before)
    word = Word(
        word="쩨큐시험어",
        abbreviation="ZZQ",
        english="Synthetic",
        definition="합성 시험",
        is_classifier=False,
    )
    after = design_rules_node(root=DEFAULT_ROOT, additional_words=(word,))(graph)["rule_findings"]
    assert not any(f.rule_code == "SC-01" for f in after)
    assert design_rules_node(root=DEFAULT_ROOT)(graph)["rule_findings"] == before


def test_technical_identifier_notices_do_not_block_or_duplicate_sc01():
    graph = state(used=True)
    design = graph["design"]
    entity = design.entities[0]
    entity = entity.evolve(
        name="미등록업무", attributes=(entity.attributes[0].evolve(name="미등록업무번호"),)
    )
    design = design.evolve(entities=(entity,), normalized=None)
    result = normalize_from_state({"design": design})
    assert isinstance(result, Normalized)
    graph["design"] = design.evolve(normalized=result.model)
    checked = design_rules_node(root=DEFAULT_ROOT)(graph)
    notices = [f for f in checked["rule_findings"] if f.kind == "technical_identifier"]
    assert len(notices) == 2
    assert all(f.severity == "minor" for f in notices)
    assert not checked["requires_manual_review"]
    assert not any(f.rule_code == "SC-01" for f in checked["rule_findings"])
