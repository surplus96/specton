"""#17: 실제 정리 함수를 그래프 상태로 연결한다. #15 분류 정책은 주입한다."""

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.codegen.model import Normalized, NormalizeFailed, Problem, ProblemCode, problem
from specton.codegen.naming import DEFAULT_PACK_ROOT
from specton.codegen.normalize_step import normalize_from_state
from specton.contracts import DesignState, Entity, Finding, Requirement
from specton.contracts.base import TargetStage
from specton.contracts.state import VersionInfo
from specton.graph import GraphState, build_graph, initial_state
from specton.normalization_node import FailureReview, normalization_node
from specton.packs.build import read_yaml
from specton.persistence.db import checkpoint_serde


def _design(*, keyed: bool = True) -> DesignState:
    req = Requirement(
        id="REQ-01", source_ref={"file_format": "csv", "row": 2}, type="FR",
        text="설비는 설비코드로 구분한다", draft_text="설비는 설비코드로 구분한다",
        analysis_version=1,
    )  # fmt: skip
    entity = Entity.model_validate({
        "id": "ENT-eq", "pack": "maintenance", "name": "설비", "description": "설비",
        "req_ids": ["REQ-01"], "attributes": [{
            "id": "ATTR-eq", "name": "설비코드", "data_type": "varchar", "length": 10,
            "is_key": keyed, "nullable": False, "req_ids": ["REQ-01"],
        }],
    })  # fmt: skip
    version = str(read_yaml(DEFAULT_PACK_ROOT / "maintenance/manifest.yaml")["version"])
    return DesignState(
        run_id="normalize-node", requirements=(req,), entities=(entity,),
        versions=VersionInfo(pack_id="maintenance", pack_version=version),
    )  # fmt: skip


def _finding(design: DesignState) -> Finding:
    return Finding(
        id="RULE-03-1", source="rule", rule_code="RULE-03", kind="no_primary_key",
        severity="critical", targets=({"kind": "entity", "id": "ENT-eq"},),
        evidence=({"quote": "설계에 기본 키가 없습니다"},), suggestion="키를 보완한다",
        target_stage=TargetStage.DATA_MODEL, fingerprint="missing-key", iteration=design.iteration,
    )  # fmt: skip


def _must_not_classify(*args: Any) -> FailureReview:
    pytest.fail("성공 또는 실행 오류를 규칙 지적으로 변환했습니다")


def _stored(design: DesignState) -> DesignState:
    result = normalize_from_state({"design": design})
    assert isinstance(result, Normalized)
    return design.evolve(normalized=result.model)


def test_success_sets_the_model_and_clears_failure_metadata() -> None:
    design = _design()
    state = initial_state(design)
    state.update(
        normalization_failed=True, requires_manual_review=True, rule_findings=(_finding(design),)
    )

    update = normalization_node(_must_not_classify, root=DEFAULT_PACK_ROOT)(state)

    expected = normalize_from_state(state)
    assert isinstance(expected, Normalized)
    assert update["design"].normalized == expected.model
    assert update["normalization_failed"] is False
    assert update["requires_manual_review"] is False
    assert update["rule_findings"] == ()
    assert design.normalized is None


@pytest.mark.parametrize("manual", [False, True])
def test_failure_passes_problems_to_the_mapper_and_removes_the_old_model(manual: bool) -> None:
    old = _stored(_design())
    broken = old.evolve(entities=_design(keyed=False).entities)
    seen: list[ProblemCode] = []

    def classify(design: DesignState, problems: tuple[Problem, ...]) -> FailureReview:
        assert design.normalized is None
        seen.extend(p.code for p in problems)
        return FailureReview(findings=(_finding(design),), requires_manual_review=manual)

    update = normalization_node(classify, root=DEFAULT_PACK_ROOT)(initial_state(broken))

    assert seen == [ProblemCode.NO_PRIMARY_KEY]
    assert update["design"].normalized is None
    assert update["normalization_failed"] is True
    assert update["requires_manual_review"] is manual
    assert update["rule_findings"] == (_finding(broken),)
    assert broken.normalized == old.normalized


def test_configured_root_is_used_instead_of_the_default_pack(tmp_path: Path) -> None:
    for pack in ("common", "maintenance"):
        shutil.copytree(DEFAULT_PACK_ROOT / pack, tmp_path / pack)
    path = tmp_path / "maintenance/terms.yaml"
    terms = read_yaml(path)
    for term in terms["terms"]:
        if term["term"] == "설비코드":
            term["physical_name"] = "CUSTOM_EQPM_CD"
    path.write_text(yaml.safe_dump(terms, allow_unicode=True), encoding="utf-8")

    update = normalization_node(_must_not_classify, root=tmp_path)(initial_state(_design()))

    (table,) = update["design"].normalized.tables
    assert table.columns[0].physical_name == "custom_eqpm_cd"


def test_recorded_pack_mismatch_does_not_enter_the_rule_mapper() -> None:
    design = _design().evolve(versions=VersionInfo(pack_id="maintenance", pack_version="old"))

    with pytest.raises(ValueError, match="pack_mismatch"):
        normalization_node(_must_not_classify, root=DEFAULT_PACK_ROOT)(initial_state(design))


def test_bad_naming_configuration_remains_an_execution_error(tmp_path: Path) -> None:
    for pack in ("common", "maintenance"):
        shutil.copytree(DEFAULT_PACK_ROOT / pack, tmp_path / pack)
    path = tmp_path / "common/naming.yaml"
    naming = read_yaml(path)
    naming["table"]["prefix"] = "NOT_SUPPORTED"
    path.write_text(yaml.safe_dump(naming, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match=r"naming\.yaml"):
        normalization_node(_must_not_classify, root=tmp_path)(initial_state(_design()))


@pytest.mark.parametrize("code", [ProblemCode.PACK_MISMATCH, ProblemCode.OUTPUT_TRACE])
def test_execution_problems_take_precedence_over_manual_problems(
    monkeypatch: pytest.MonkeyPatch, code: ProblemCode
) -> None:
    from specton import normalization_node as module

    failed = NormalizeFailed(
        problems=(
            problem(ProblemCode.UNRESOLVED_NAME, "ENT-eq", "사전 없음"),
            problem(code, "ENT-eq", "실행 오류"),
        )
    )
    monkeypatch.setattr(module, "normalize_from_state", lambda *args, **kwargs: failed)

    with pytest.raises(ValueError, match=code.value):
        normalization_node(_must_not_classify, root=DEFAULT_PACK_ROOT)(initial_state(_design()))


def test_empty_failure_mapping_is_rejected() -> None:
    def empty(*args: Any) -> FailureReview:
        return FailureReview(findings=(), requires_manual_review=True)

    with pytest.raises(ValueError, match="차단 규칙 지적"):
        normalization_node(empty, root=DEFAULT_PACK_ROOT)(initial_state(_design(keyed=False)))


def test_ambiguous_manual_flag_is_rejected() -> None:
    def invalid(design: DesignState, problems: tuple[Problem, ...]) -> FailureReview:
        return {"findings": (_finding(design),), "requires_manual_review": "false"}  # type: ignore[typeddict-item]

    with pytest.raises(ValueError, match="bool"):
        normalization_node(invalid, root=DEFAULT_PACK_ROOT)(initial_state(_design(keyed=False)))


def test_empty_problem_result_is_an_execution_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from specton import normalization_node as module

    monkeypatch.setattr(
        module, "normalize_from_state", lambda *args, **kwargs: NormalizeFailed(problems=())
    )
    with pytest.raises(ValueError, match="문제 목록"):
        normalization_node(_must_not_classify, root=DEFAULT_PACK_ROOT)(initial_state(_design()))


@pytest.mark.parametrize(("decision", "pending"), [("D4", False), ("D13", False), ("D5", True)])
def test_problem_classification_metadata_is_forwarded_unchanged(
    monkeypatch: pytest.MonkeyPatch, decision: str, pending: bool
) -> None:
    from specton import normalization_node as module

    code = ProblemCode.UNRESOLVED_NAME if pending else ProblemCode.FK_COLUMN_CONFLICT
    expected = problem(code, "REL-01", "충돌", decision=decision, pending=pending)
    monkeypatch.setattr(
        module,
        "normalize_from_state",
        lambda *args, **kwargs: NormalizeFailed(problems=(expected,)),
    )
    received: list[Problem] = []

    def classify(design: DesignState, problems: tuple[Problem, ...]) -> FailureReview:
        received.extend(problems)
        return FailureReview(findings=(_finding(design),), requires_manual_review=True)

    normalization_node(classify, root=DEFAULT_PACK_ROOT)(initial_state(_design()))
    assert received == [expected]


@pytest.mark.parametrize("manual", [False, True])
def test_actual_failure_reaches_the_existing_graph_gate(manual: bool) -> None:
    def classify(design: DesignState, problems: tuple[Problem, ...]) -> FailureReview:
        return FailureReview(findings=(_finding(design),), requires_manual_review=manual)

    def repair(state: GraphState) -> dict[str, Any]:
        if state["design"].revision:
            return {"design": state["design"].evolve(entities=_design().entities)}
        return {}

    graph = build_graph(
        {"a03": repair, "normalize": normalization_node(classify, root=DEFAULT_PACK_ROOT)},
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
    )
    result = graph.invoke(
        initial_state(_design(keyed=False)), {"configurable": {"thread_id": "failure"}}
    )
    assert result["design"].status == "awaiting_review"
    if manual:
        assert result["design"].revision == 0
        assert result["design"].normalized is None
        assert result["__interrupt__"][0].value["hitl_reason"] == "manual_review"
    else:
        assert result["design"].revision == 1
        assert result["design"].normalized is not None
        assert result["design"].findings == ()


@pytest.mark.parametrize("revise", [False, True], ids=["automatic", "explicit"])
def test_rework_clears_the_stored_model_before_the_design_node(revise: bool) -> None:
    seen: list[DesignState] = []
    start = _stored(_design())

    def a03(state: GraphState) -> dict[str, Any]:
        seen.append(state["design"])
        return {}

    def rules(state: GraphState) -> dict[str, Any]:
        findings = (
            (_finding(state["design"]),) if not revise and state["design"].revision == 0 else ()
        )
        return {"rule_findings": findings}

    graph = build_graph(
        {"a03": a03, "rules": rules, "a09": lambda state: {"router_stage": TargetStage.DATA_MODEL}},
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
    )
    config = {"configurable": {"thread_id": "normalize-node"}}
    graph.invoke(initial_state(start), config)
    if revise:
        graph.invoke(
            Command(resume={"kind": "review", "decision": "revise", "feedback": "보완"}), config
        )

    assert seen[0].normalized == start.normalized
    assert seen[1].revision == 1 and seen[1].normalized is None
    assert start.normalized is not None
