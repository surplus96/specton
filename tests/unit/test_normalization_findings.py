"""정리 실패 → 규칙 지적 (#15). 실제 정리 코드가 낸 문제로 변환 결과를 확인한다."""

import time
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from specton.codegen.model import NormalizeFailed, Problem, ProblemCode, problem
from specton.codegen.naming import DEFAULT_PACK_ROOT, TermInfo
from specton.codegen.normalize import normalize
from specton.contracts import DesignState, Entity, Requirement
from specton.contracts.base import SqlType, TargetStage
from specton.contracts.findings import FindingSource, Severity
from specton.contracts.state import VersionInfo
from specton.graph import GraphState, build_graph, initial_state
from specton.normalization_node import normalization_node
from specton.packs.build import read_yaml
from specton.persistence.db import checkpoint_serde
from specton.review.normalization_findings import (
    failure_mapper,
    map_normalization_failure,
    rule_severities,
)
from tests.unit.test_normalize import (
    LEXICON,
    PACK,
    RECEIPT,
    RULES,
    RULES_SELF,
    SUPPLIER,
    WAREHOUSE,
    FixtureLexicon,
    _attr,
    _design,
    _entity,
    _rel,
)

SEVERITIES = {f"RULE-0{n}": Severity.CRITICAL for n in range(1, 8)}
STAGES = list(TargetStage)


def _versioned(design: DesignState) -> DesignState:
    return design.evolve(versions=VersionInfo(pack_id=PACK.name, pack_version=PACK.version))


def _map(
    entities: list[Entity], rels: list[Any], *, lexicon: Any = LEXICON, rules: Any = RULES
) -> tuple[DesignState, tuple[Problem, ...], Any]:
    """실제 정리를 돌려 실패 문제를 얻고 변환한다."""
    design = _versioned(_design(entities, rels))
    result = normalize(design, pack=PACK, lexicon=lexicon, rules=rules)
    assert isinstance(result, NormalizeFailed), result
    review = map_normalization_failure(design, result.problems, severities=SEVERITIES)
    return design, result.problems, review


def _targets(finding: Any) -> list[tuple[str, str]]:
    return [(t.kind, t.id) for t in finding.targets]


NO_KEY = _entity("ENT-wh", "창고", _attr("ATTR-wh-nm", "창고명", length=200))
OTHER = _entity("ENT-ot", "출고", _attr("ATTR-ot-no", "출고번호", is_key=True))

# (이름, 엔티티, 관계, 사전, 명명 규칙, 기대: 문제 코드, 규칙, 종류, 대상, 복귀 단계, 사람 확인)
CASES: list[tuple[Any, ...]] = [
    ("no_primary_key", [NO_KEY], [], LEXICON, RULES,
     ProblemCode.NO_PRIMARY_KEY, "RULE-03", "no_primary_key",
     [("entity", "ENT-wh")], TargetStage.DATA_MODEL, False),
    ("domain_type_mismatch",
     [_entity("ENT-wh", "창고", _attr("ATTR-wh-cd", "창고코드", is_key=True))], [],
     FixtureLexicon(terms={"창고코드": TermInfo("WRHUS_CD", "코드C10", data_type=SqlType.CHAR)}),
     RULES, ProblemCode.DOMAIN_TYPE_MISMATCH, "RULE-03", "domain_type_mismatch",
     [("attribute", "ATTR-wh-cd")], TargetStage.DATA_MODEL, False),
    ("optional_identifying", [WAREHOUSE, RECEIPT],
     [_rel("REL-01", "ENT-wh", "ENT-rc", identifying=True, optional=True)], LEXICON, RULES,
     ProblemCode.OPTIONAL_IDENTIFYING, "RULE-04", "optional_identifying_conflict",
     [("relationship", "REL-01")], TargetStage.DATA_MODEL, False),
    ("identifying_cycle", [WAREHOUSE, RECEIPT],
     [_rel("REL-01", "ENT-wh", "ENT-rc", identifying=True),
      _rel("REL-02", "ENT-rc", "ENT-wh", identifying=True)], LEXICON, RULES,
     ProblemCode.IDENTIFYING_CYCLE, "RULE-04", "identifying_cycle",
     [("entity", "ENT-rc"), ("entity", "ENT-wh")], TargetStage.DATA_MODEL, False),
    ("required_self_reference", [WAREHOUSE], [_rel("REL-01", "ENT-wh", "ENT-wh")],
     LEXICON, RULES_SELF, ProblemCode.REQUIRED_SELF_REFERENCE, "RULE-04",
     "required_self_reference", [("relationship", "REL-01")], TargetStage.DATA_MODEL, False),
    ("unsupported_relationship", [WAREHOUSE, SUPPLIER],
     [_rel("REL-01", "ENT-wh", "ENT-sp", cardinality="N:M", identifying=True)], LEXICON, RULES,
     ProblemCode.UNSUPPORTED_RELATIONSHIP, "RULE-04", "unsupported_relationship",
     [("relationship", "REL-01")], TargetStage.DATA_MODEL, False),
    ("fk_conflict_d13",
     [WAREHOUSE, _entity("ENT-rc", "입고", _attr("ATTR-rc-no", "입고번호", is_key=True),
                         _attr("ATTR-rc-wh", "창고코드", nullable=False))],
     [_rel("REL-01", "ENT-wh", "ENT-rc")], LEXICON, RULES,
     ProblemCode.FK_COLUMN_CONFLICT, "RULE-04", "fk_column_conflict:D13",
     [("relationship", "REL-01")], TargetStage.DATA_MODEL, False),
    ("fk_conflict_d4",
     [WAREHOUSE, _entity("ENT-is", "출고", _attr("ATTR-is-wh", "창고코드", is_key=True))],
     [_rel("REL-01", "ENT-wh", "ENT-is", cardinality="N:M")], LEXICON, RULES,
     ProblemCode.FK_COLUMN_CONFLICT, "RULE-05", "fk_column_conflict:D4",
     [("relationship", "REL-01")], None, True),
    ("unresolved_table_name",
     [_entity("ENT-x", "미등록", _attr("ATTR-x-cd", "창고코드", is_key=True))], [], LEXICON,
     RULES, ProblemCode.UNRESOLVED_NAME, "RULE-05", "unresolved_name",
     [("entity", "ENT-x")], None, True),
    ("unresolved_column_name",
     [_entity("ENT-wh", "창고", _attr("ATTR-wh-cd", "창고코드", is_key=True),
              _attr("ATTR-wh-x", "미등록칸"))], [], LEXICON, RULES,
     ProblemCode.UNRESOLVED_NAME, "RULE-05", "unresolved_name",
     [("attribute", "ATTR-wh-x")], None, True),
    ("naming_rule_missing", [WAREHOUSE], [_rel("REL-01", "ENT-wh", "ENT-wh", optional=True)],
     LEXICON, RULES, ProblemCode.NAMING_RULE_MISSING, "RULE-05", "naming_rule_missing",
     [("relationship", "REL-01")], None, True),
    ("reserved_word",
     [_entity("ENT-or", "주문", _attr("ATTR-or-cd", "창고코드", is_key=True))], [],
     FixtureLexicon(words={"주문": "ORDER"}), RULES,
     ProblemCode.RESERVED_WORD, "RULE-05", "reserved_word",
     [("entity", "ENT-or")], None, True),
    ("name_too_long",
     [_entity("ENT-lg", "긴이름", _attr("ATTR-lg-cd", "창고코드", is_key=True))], [],
     FixtureLexicon(words={"긴이름": "X" * 70}), RULES,
     ProblemCode.NAME_TOO_LONG, "RULE-05", "name_too_long",
     [("entity", "ENT-lg")], None, True),
    ("duplicate_table_name",
     [WAREHOUSE, _entity("ENT-bx", "보관소", _attr("ATTR-bx-cd", "입고번호", is_key=True))], [],
     FixtureLexicon(words={"보관소": "WRHUS"}), RULES,
     ProblemCode.DUPLICATE_NAME, "RULE-05", "duplicate_name",
     [("entity", "ENT-bx"), ("entity", "ENT-wh")], None, True),
]  # fmt: skip


@pytest.mark.parametrize(
    ("name", "entities", "rels", "lexicon", "rules", "code", "rule", "kind", "targets", "stage",
     "manual"),
    CASES,
    ids=[c[0] for c in CASES],
)  # fmt: skip
def test_each_problem_from_real_normalization_becomes_one_rule_finding(
    name: str, entities: list[Entity], rels: list[Any], lexicon: Any, rules: Any,
    code: ProblemCode, rule: str, kind: str, targets: list[tuple[str, str]],
    stage: TargetStage | None, manual: bool,
) -> None:  # fmt: skip
    design, problems, review = _map(entities, rels, lexicon=lexicon, rules=rules)
    assert [p.code for p in problems] == [code]
    (finding,) = review["findings"]
    assert finding.source is FindingSource.RULE
    assert finding.severity is Severity.CRITICAL
    assert finding.rule_code == rule
    assert finding.reviewer_id is None
    assert finding.kind == kind
    assert sorted(_targets(finding)) == sorted(targets)
    assert finding.target_stage is stage
    assert finding.evidence[0].quote == problems[0].detail
    assert finding.suggestion
    assert finding.iteration == design.iteration
    assert review["requires_manual_review"] is manual


def test_every_problem_is_kept_and_manual_review_takes_precedence() -> None:
    """재작업 문제와 사람 확인 문제가 함께 있으면 하나도 빼지 않고 사람 확인으로 보낸다."""
    entities = [NO_KEY, _entity("ENT-x", "미등록", _attr("ATTR-x-cd", "창고코드", is_key=True))]
    _, problems, review = _map(entities, [])
    assert len(review["findings"]) == len(problems) == 2
    assert {f.rule_code for f in review["findings"]} == {"RULE-03", "RULE-05"}
    assert review["requires_manual_review"] is True
    ids = [f.id for f in review["findings"]]
    assert len(set(ids)) == len(ids)


def test_automatic_problems_only_return_to_the_earliest_stage_of_each_target() -> None:
    _, _, review = _map([NO_KEY, OTHER], [_rel("REL-01", "ENT-wh", "ENT-ot")])
    assert review["requires_manual_review"] is False
    assert all(f.target_stage is TargetStage.DATA_MODEL for f in review["findings"])


def _design_with_versions() -> DesignState:
    return _versioned(_design([WAREHOUSE, RECEIPT], [_rel("REL-01", "ENT-wh", "ENT-rc")]))


def _trace(target: str, detail: str) -> Problem:
    return problem(ProblemCode.INPUT_TRACE, target, detail)


def test_input_trace_keeps_its_detail_kind_so_different_problems_are_not_merged() -> None:
    """같은 대상의 다른 추적 문제는 종류·지문이 달라 검토 단계에서 하나로 합쳐지지 않는다."""
    design = _design_with_versions()
    review = map_normalization_failure(
        design,
        (
            _trace("ENT-rc", "entity missing_req_ids: req_ids가 비었습니다"),
            _trace("ENT-rc", "entity unknown_req_id: 현재 revision에 없는 REQ-99를 참조합니다"),
            _trace("REQ-01", "requirement duplicate_id: ID가 중복됩니다"),
            _trace("ENT-wh", "entity unknown_entity_ref: 없는 엔티티를 가리킵니다"),
        ),
        severities=SEVERITIES,
    )
    first, second, third, fourth = review["findings"]
    assert (first.rule_code, first.kind) == ("RULE-02", "input_trace:missing_req_ids")
    assert (second.rule_code, second.kind) == ("RULE-01", "input_trace:unknown_req_id")
    assert first.targets == second.targets
    assert first.fingerprint != second.fingerprint
    assert third.target_stage is TargetStage.REQUIREMENTS
    assert _targets(third) == [("requirement", "REQ-01")]
    assert fourth.kind == "input_trace:unknown_entity_ref"
    assert review["requires_manual_review"] is False


def test_function_trace_returns_to_the_function_stage() -> None:
    design = _design_with_versions()
    function = {
        "id": "FUNC-01", "name": "입고 등록", "description": "입고를 등록한다",
        "priority_rationale": "REQ-01 문장", "req_ids": ["REQ-01"],
    }  # fmt: skip
    design = design.evolve(functions=[function])
    review = map_normalization_failure(
        design,
        (_trace("FUNC-01", "function unknown_req_id: REQ-99"),),
        severities=SEVERITIES,
    )
    (finding,) = review["findings"]
    assert finding.target_stage is TargetStage.FUNCTIONS
    assert _targets(finding) == [("function", "FUNC-01")]


LONG_KEY = "X" * 61  # 접두어 "up_"를 붙이면 64바이트라 63바이트 한도를 넘는다


def _long_keyed(entity_id: str, name: str) -> Entity:
    return _entity(entity_id, name, _attr(f"ATTR-{entity_id}", "긴키", is_key=True))


def test_self_reference_fk_name_problem_points_at_the_relationship() -> None:
    """자기참조 FK 칸 이름이 너무 길면 정리 코드가 그 관계를 대상으로 넣고, 그대로 관계로 잇는다."""
    lexicon = FixtureLexicon(words={"긴키": LONG_KEY})
    _, problems, review = _map(
        [_long_keyed("ENT-wh", "창고")],
        [_rel("REL-01", "ENT-wh", "ENT-wh", optional=True)],
        lexicon=lexicon,
        rules=RULES_SELF,
    )
    assert [(p.code, p.target) for p in problems] == [(ProblemCode.NAME_TOO_LONG, "REL-01")]
    (finding,) = review["findings"]
    assert _targets(finding) == [("relationship", "REL-01")]
    assert review["requires_manual_review"] is True


@pytest.mark.parametrize(
    "item",
    [
        problem(ProblemCode.NO_PRIMARY_KEY, "ENT-없음", "없는 대상"),
        problem(ProblemCode.DUPLICATE_NAME, "ENT-wh,TBL-없음", "하나만 없는 대상"),
        problem(ProblemCode.NO_PRIMARY_KEY, "", "대상 없음"),
    ],
    ids=["unknown", "one_of_many_unknown", "empty"],
)
def test_unknown_target_stops_instead_of_linking_to_another_object(item: Problem) -> None:
    with pytest.raises(ValueError, match="대상"):
        map_normalization_failure(_design_with_versions(), (item,), severities=SEVERITIES)


@pytest.mark.parametrize(
    ("item", "message"),
    [
        (problem(ProblemCode.PACK_MISMATCH, "ENT-wh", "팩 불일치"), "규칙 지적으로 바꾸지 않는"),
        (problem(ProblemCode.OUTPUT_TRACE, "ENT-wh", "결과 검사"), "규칙 지적으로 바꾸지 않는"),
        (problem(ProblemCode.FK_COLUMN_CONFLICT, "REL-01", "결정 없음"), "결정 번호"),
        (problem(ProblemCode.FK_COLUMN_CONFLICT, "REL-01", "D99", decision="D99"), "결정 번호"),
        (_trace("ENT-wh", "알 수 없는 형식"), "세부 유형"),
        (_trace("ENT-wh", "entity made_up_kind: 설명"), "세부 유형"),
    ],
    ids=["pack_mismatch", "output_trace", "fk_no_decision", "fk_unknown_decision",
         "trace_format", "trace_kind"],
)  # fmt: skip
def test_unsupported_problem_stops_with_a_clear_error(item: Problem, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        map_normalization_failure(_design_with_versions(), (item,), severities=SEVERITIES)


def test_missing_severity_pack_id_or_problems_stop() -> None:
    design = _design_with_versions()
    item = problem(ProblemCode.NO_PRIMARY_KEY, "ENT-wh", "PK 없음")
    with pytest.raises(ValueError, match="RULE-03의 심각도"):
        map_normalization_failure(design, (item,), severities={})
    with pytest.raises(ValueError, match="팩 ID"):
        map_normalization_failure(
            design.evolve(versions=VersionInfo()), (item,), severities=SEVERITIES
        )
    with pytest.raises(ValueError, match="문제 목록"):
        map_normalization_failure(design, (), severities=SEVERITIES)


def test_severities_come_from_the_common_rules_file() -> None:
    severities = rule_severities(root=DEFAULT_PACK_ROOT)
    rules = read_yaml(DEFAULT_PACK_ROOT / "common/rules.yaml")["rules"]
    assert severities == {r["id"]: Severity(r["severity"]) for r in rules}


# ── R1 정리 노드에 연결 (#17) ─────────────────────────────────────────


def _maintenance(*, entity_name: str = "설비", keyed: bool = True) -> DesignState:
    req = Requirement(
        id="REQ-01", source_ref={"file_format": "csv", "row": 2}, type="FR",
        text="설비는 설비코드로 구분한다", draft_text="설비는 설비코드로 구분한다",
        analysis_version=1,
    )  # fmt: skip
    entity = Entity.model_validate({
        "id": "ENT-eq", "pack": "maintenance", "name": entity_name, "description": "설비",
        "req_ids": ["REQ-01"], "attributes": [{
            "id": "ATTR-eq", "name": "설비코드", "data_type": "varchar", "length": 10,
            "is_key": keyed, "nullable": False, "req_ids": ["REQ-01"],
        }],
    })  # fmt: skip
    version = str(read_yaml(DEFAULT_PACK_ROOT / "maintenance/manifest.yaml")["version"])
    return DesignState(
        run_id="normalize-findings", requirements=(req,), entities=(entity,),
        versions=VersionInfo(pack_id="maintenance", pack_version=version),
    )  # fmt: skip


def _node() -> Any:
    root = DEFAULT_PACK_ROOT
    return normalization_node(failure_mapper(rule_severities(root=root)), root=root)


@pytest.mark.parametrize(
    ("design", "manual", "rule"),
    [
        (_maintenance(keyed=False), False, "RULE-03"),
        (_maintenance(entity_name="미등록설비"), True, "RULE-05"),
    ],
    ids=["automatic", "manual"],
)
def test_node_returns_the_mapped_findings_for_a_real_failure(
    design: DesignState, manual: bool, rule: str
) -> None:
    """노드 반환값만 확인한다 (실제 실행 팩·정리 코드·변환기, 그래프 분기는 아래 테스트)."""
    out = _node()(initial_state(design))
    assert out["normalization_failed"] is True
    assert out["requires_manual_review"] is manual
    assert [f.rule_code for f in out["rule_findings"]] == [rule]
    assert out["design"].normalized is None


@pytest.mark.parametrize("manual", [False, True], ids=["automatic", "manual"])
def test_real_failure_reaches_the_graph_branch(manual: bool) -> None:
    """실제 변환기를 넣은 정리 노드로 그래프를 돌려, 자동 재작업과 사람 확인 분기에 도착하는지 본다.

    나머지 노드는 그래프의 기본 빈 노드(stub)이고, 재작업 때 A03 자리에서 설계를 고친다.
    """
    broken = _maintenance(entity_name="미등록설비") if manual else _maintenance(keyed=False)

    def repair(state: GraphState) -> dict[str, Any]:
        if state["design"].revision:
            return {"design": state["design"].evolve(entities=_maintenance().entities)}
        return {}

    graph = build_graph(
        {"a03": repair, "normalize": _node()},
        checkpointer=InMemorySaver(serde=checkpoint_serde()),
    )
    result = graph.invoke(initial_state(broken), {"configurable": {"thread_id": "findings"}})
    assert result["design"].status == "awaiting_review"
    if manual:
        assert result["design"].revision == 0
        assert result["__interrupt__"][0].value["hitl_reason"] == "manual_review"
        assert [f.rule_code for f in result["design"].findings] == ["RULE-05"]
    else:
        assert result["design"].revision == 1
        assert result["design"].normalized is not None
        assert result["design"].findings == ()


# ── #15 검토 반영: 종류별 대상 찾기, 막힌 관계를 펼치지 않음 ──────────────


def test_objects_of_different_kinds_may_share_an_id() -> None:
    """요구사항과 기능 ID가 같아도(계약·추적 검사가 허용) 관계없는 PK 지적은 그대로 변환된다."""
    function = {
        "id": "REQ-01", "name": "창고 등록", "description": "창고를 등록한다",
        "priority_rationale": "REQ-01 문장", "req_ids": ["REQ-01"],
    }  # fmt: skip
    design = _versioned(_design([NO_KEY], [])).evolve(functions=[function])
    result = normalize(design, pack=PACK, lexicon=LEXICON, rules=RULES)
    assert isinstance(result, NormalizeFailed)
    review = map_normalization_failure(design, result.problems, severities=SEVERITIES)
    (finding,) = review["findings"]
    assert _targets(finding) == [("entity", "ENT-wh")]

    traced = map_normalization_failure(
        design,
        (
            _trace("REQ-01", "function unknown_req_id: REQ-99"),
            _trace("REQ-01", "requirement duplicate_id: ID가 중복됩니다"),
        ),
        severities=SEVERITIES,
    )
    as_function, as_requirement = traced["findings"]
    assert _targets(as_function) == [("function", "REQ-01")]
    assert as_function.target_stage is TargetStage.FUNCTIONS
    assert _targets(as_requirement) == [("requirement", "REQ-01")]
    assert as_requirement.target_stage is TargetStage.REQUIREMENTS


def test_blocked_identifying_chains_are_not_expanded() -> None:
    """단계마다 같은 부모를 두 번 식별 참조하는 사슬. 정리가 FK 이름 충돌로 막은 키를 펼치지 않는다.

    이전 방식은 엔티티 15개·관계 28개에서 변환에만 1초 넘게 걸렸다 (#15 검토 재현).
    """
    count = 15
    words = {f"단{i}": f"STEP{i}" for i in range(count)}
    words |= {f"단{i}번호": f"STEP{i}_NO" for i in range(count)}
    entities = [
        _entity(f"ENT-{i}", f"단{i}", _attr(f"ATTR-{i}", f"단{i}번호", is_key=True))
        for i in range(count)
    ]
    rels = [
        _rel(f"REL-{i}-{side}", f"ENT-{i - 1}", f"ENT-{i}", identifying=True)
        for i in range(1, count)
        for side in ("a", "b")
    ]
    design = _versioned(_design(entities, rels))
    result = normalize(design, pack=PACK, lexicon=FixtureLexicon(words=words), rules=RULES)
    assert isinstance(result, NormalizeFailed)
    started = time.perf_counter()
    review = map_normalization_failure(design, result.problems, severities=SEVERITIES)
    elapsed = time.perf_counter() - started
    assert len(review["findings"]) == len(result.problems)
    assert elapsed < 0.2, elapsed


def test_self_reference_name_problem_does_not_expand_an_unrelated_blocked_chain() -> None:
    """막힌 식별 사슬 끝의 자기참조와 따로 있는 정상 엔티티의 자기참조 FK 이름 오류 (#15 검토).

    정상 엔티티의 문제를 잇기 위해 관계없는 막힌 사슬을 펼치지 않는다.
    """
    count = 15
    words = {f"단{i}": f"STEP{i}" for i in range(count)}
    words |= {f"단{i}번호": f"STEP{i}_NO" for i in range(count)}
    words |= {"긴키": LONG_KEY}
    entities = [
        _entity(f"ENT-{i}", f"단{i}", _attr(f"ATTR-{i}", f"단{i}번호", is_key=True))
        for i in range(count)
    ]
    entities.append(_long_keyed("ENT-ok", "창고"))
    rels = [
        _rel(f"REL-{i}-{side}", f"ENT-{i - 1}", f"ENT-{i}", identifying=True)
        for i in range(1, count)
        for side in ("a", "b")
    ]
    rels.append(_rel("REL-end", f"ENT-{count - 1}", f"ENT-{count - 1}", optional=True))
    rels.append(_rel("REL-ok", "ENT-ok", "ENT-ok", optional=True))
    design = _versioned(_design(entities, rels))
    result = normalize(design, pack=PACK, lexicon=FixtureLexicon(words=words), rules=RULES_SELF)
    assert isinstance(result, NormalizeFailed)
    assert (ProblemCode.NAME_TOO_LONG, "REL-ok") in {(p.code, p.target) for p in result.problems}
    started = time.perf_counter()
    review = map_normalization_failure(design, result.problems, severities=SEVERITIES)
    elapsed = time.perf_counter() - started
    assert len(review["findings"]) == len(result.problems)
    too_long = [f for f in review["findings"] if f.kind == "name_too_long"]
    assert [_targets(f) for f in too_long] == [[("relationship", "REL-ok")]]
    assert elapsed < 0.2, elapsed


def test_only_many_to_many_relationships_count_as_junction_tables() -> None:
    """엔티티와 그 비식별 자기참조가 같은 ID여도, 연결 테이블이 없는 관계는 테이블 대상이 아니다."""
    entity = _entity("REL-01", "미등록", _attr("ATTR-x-cd", "창고코드", is_key=True))
    _, problems, review = _map(
        [entity], [_rel("REL-01", "REL-01", "REL-01", optional=True)], rules=RULES_SELF
    )
    unresolved = [f for f in review["findings"] if f.kind == "unresolved_name"]
    assert [_targets(f) for f in unresolved] == [[("entity", "REL-01")]]
    assert {p.code for p in problems} == {ProblemCode.UNRESOLVED_NAME}
