"""TC-A06: A06 데이터 누락 검토 관점 (설정형 리뷰어로 실행).

판단 자체는 LLM이 하므로 여기서는 관점 설정이 프롬프트에 들어가는지, 설계 전체가 검토 입력에
들어가는지, 지적이 공통 Finding으로 기록되는지, 형식·근거가 틀린 응답을 거절하는지를
고정 응답으로 확인한다.
"""

import json
from pathlib import Path

from specton.config import Settings
from specton.contracts import DesignState, Entity, FindingDraft, Function, Requirement
from specton.llm.stub import reply, stub_client
from specton.nodes.common import unwrap_data
from specton.review.perspective import PERSPECTIVES_DIR, load_perspective, load_perspectives
from specton.review.reviewer import ReviewOutput, review_perspective

A06 = load_perspective(PERSPECTIVES_DIR / "A06.yaml")

PART_TEXT = "작업에는 사용한 부품의 코드·이름·단위·수량·적용 단가를 남긴다."
TEAM_TEXT = "한 기술자는 여러 팀에 소속될 수 있다. 탈퇴한 소속도 가입·탈퇴 일자를 남긴다."


def _requirement(req_id: str, text: str, row: int) -> Requirement:
    return Requirement(
        id=req_id,
        source_ref={"file_format": "xlsx", "sheet": "requirements", "row": row},
        text=text,
        draft_text=text,
        type="FR",
        analysis_version=1,
    )


def _attr(attr_id: str, name: str, req_id: str, **extra: object) -> dict[str, object]:
    base: dict[str, object] = {"id": attr_id, "name": name, "req_ids": [req_id]}
    if "data_type" not in extra:
        base |= {"data_type": "varchar", "length": 20}
    return base | extra


def _entity(ent_id: str, name: str, req_id: str, attributes: list[dict[str, object]]) -> Entity:
    return Entity(
        id=ent_id,
        pack="maintenance",
        name=name,
        description=name,
        attributes=attributes,
        req_ids=[req_id],
    )


def _missing_state() -> DesignState:
    """적용 단가를 저장할 속성이 어느 엔티티에도 없는 설계."""
    part_use = _entity(
        "ENT-01",
        "사용부품실적",
        "REQ-01",
        [
            _attr("ATTR-01", "작업번호", "REQ-01", is_key=True, nullable=False),
            _attr("ATTR-02", "부품코드", "REQ-01", is_key=True, nullable=False),
            _attr("ATTR-03", "부품명", "REQ-01"),
            _attr("ATTR-04", "단위명", "REQ-01"),
            _attr("ATTR-05", "사용수량", "REQ-01", data_type="numeric", precision=10, scale=3),
        ],
    )
    record = Function(
        id="FUNC-01",
        name="사용 부품 기록",
        description="작업에 사용한 부품을 기록한다",
        req_ids=["REQ-01"],
    )
    return DesignState(
        run_id="run-1",
        requirements=[_requirement("REQ-01", PART_TEXT, 15)],
        functions=[record],
        entities=[part_use],
    )


def _satisfied_elsewhere_state() -> DesignState:
    """가입·탈퇴 일자를 기술자 엔티티가 아니라 팀소속 엔티티가 가진 설계."""
    technician = _entity(
        "ENT-01",
        "기술자",
        "REQ-01",
        [_attr("ATTR-01", "기술자번호", "REQ-01", is_key=True, nullable=False)],
    )
    membership = _entity(
        "ENT-02",
        "팀소속",
        "REQ-01",
        [
            _attr("ATTR-02", "기술자번호", "REQ-01", is_key=True, nullable=False),
            _attr("ATTR-03", "팀코드", "REQ-01", is_key=True, nullable=False),
            _attr("ATTR-04", "가입일자", "REQ-01", data_type="date", is_key=True, nullable=False),
            _attr("ATTR-05", "탈퇴일자", "REQ-01", data_type="date"),
        ],
    )
    manage = Function(
        id="FUNC-01",
        name="팀 소속 관리",
        description="기술자의 팀 가입과 탈퇴를 기록한다",
        req_ids=["REQ-01"],
    )
    return DesignState(
        run_id="run-1",
        requirements=[_requirement("REQ-01", TEAM_TEXT, 4)],
        functions=[manage],
        entities=[technician, membership],
    )


def _missing_attribute_finding() -> FindingDraft:
    return FindingDraft(
        kind="missing_attribute",
        severity="major",
        targets=[{"kind": "entity", "id": "ENT-01"}],
        evidence=[{"req_id": "REQ-01", "quote": "단위·수량·적용 단가를 남긴다"}],
        suggestion="사용부품실적 엔티티에 적용 단가 속성을 추가한다",
        target_stage="data_model",
    )


def _settings() -> Settings:
    return Settings(_env_file=None)


# 관점 설정


def test_a06_reads_requirements_functions_entities_and_relationships() -> None:
    assert set(A06.inputs) == {"requirements", "functions", "entities", "relationships"}
    assert A06.prompt_version == "a06-v6"


def test_a06_is_loaded_with_the_other_perspectives() -> None:
    assert "A06" in [p.reviewer_id for p in load_perspectives()]


def test_a06_checklist_covers_attributes_and_functions() -> None:
    checklist = " ".join(A06.checklist)

    for topic in ("속성", "동작", "기능", "엔티티", "다른 엔티티·다른 기능"):
        assert topic in checklist, topic


def test_a06_routes_missing_attributes_and_functions_to_their_stage() -> None:
    assert "data_model" in A06.instructions
    assert "functions" in A06.instructions
    assert "requirements" in A06.instructions


def test_a06_guards_do_not_overlap_the_other_perspectives() -> None:
    guards = " ".join(A06.false_positive_guards)

    for other in ("A05", "A07", "A08"):
        assert other in guards, other
    assert "요구사항에 없는" in guards


# 다른 테이블·기능에서 충족하는 경우 (#5 완료 조건)


def test_a06_prompt_keeps_the_satisfied_elsewhere_guard() -> None:
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    review_perspective(client, A06, _satisfied_elsewhere_state(), _settings())

    system = transport.sent[0].messages[0].content
    assert "다른 엔티티나 다른 기능에서 같은 요구를 충족하면 누락으로 지적하지 않는다" in system
    assert "한 곳에 없다는 사실만으로 누락이라고 하지 않는다" in system


def test_a06_prompt_marks_uncertainty_when_context_is_short() -> None:
    """TC-A06 기대: 전달 문맥이 부족하면 단정하지 않고 불확실성을 표시한다."""
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    review_perspective(client, A06, _satisfied_elsewhere_state(), _settings())

    system = transport.sent[0].messages[0].content
    assert "누락이라고 단정하지 않는다" in system
    assert "전달된 설계 안에서 찾지 못함(확인 필요)" in system


def test_a06_shows_the_whole_design_so_another_table_can_be_checked() -> None:
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    review_perspective(client, A06, _satisfied_elsewhere_state(), _settings())

    data = json.loads(unwrap_data(transport.sent[0].messages[1].content))
    entity_names = [e["name"] for e in data["entities"]]
    attribute_names = [a["name"] for e in data["entities"] for a in e["attributes"]]
    assert entity_names == ["기술자", "팀소속"]
    assert {"가입일자", "탈퇴일자"} <= set(attribute_names)
    assert [f["name"] for f in data["functions"]] == ["팀 소속 관리"]


def test_a06_accepts_no_finding_when_another_entity_satisfies_the_requirement() -> None:
    client, _ = stub_client(reply(ReviewOutput(findings=())))

    run = review_perspective(client, A06, _satisfied_elsewhere_state(), _settings())

    (result,) = run.results
    assert (result.ok, result.findings) == (True, ())


# 지적 기록과 거절


def test_a06_reports_a_missing_attribute() -> None:
    client, _ = stub_client(reply(ReviewOutput(findings=(_missing_attribute_finding(),))))

    run = review_perspective(client, A06, _missing_state(), _settings())

    (result,) = run.results
    (finding,) = result.findings
    assert (result.ok, finding.reviewer_id, finding.target_stage) == (True, "A06", "data_model")
    assert (finding.kind, finding.targets[0].id) == ("missing_attribute", "ENT-01")


def test_a06_retries_when_output_breaks_the_contract() -> None:
    client, transport = stub_client(reply("{}"), reply(ReviewOutput(findings=())))

    run = review_perspective(client, A06, _missing_state(), _settings())

    assert len(transport.sent) == 2
    assert run.results[0].ok


def test_a06_finding_without_evidence_is_rejected() -> None:
    no_evidence = _missing_attribute_finding().model_dump(mode="json") | {"evidence": []}
    bad = json.dumps({"findings": [no_evidence]}, ensure_ascii=False)
    client, _ = stub_client(reply(bad), reply(bad), reply(bad))

    run = review_perspective(client, A06, _missing_state(), _settings())

    assert (run.results[0].ok, run.results[0].error_code) == (False, "LLM_OUTPUT_INVALID")


def test_a06_sees_existing_relationship_without_requiring_an_explicit_fk_attribute() -> None:
    cases = json.loads(
        (Path(__file__).parent / "data/review_comparison_synthetic.json").read_text()
    )
    state = DesignState.model_validate(cases["cases"][0]["design"])
    client, transport = stub_client(reply(ReviewOutput(findings=())))
    review_perspective(client, A06, state, _settings())
    data = json.loads(unwrap_data(transport.sent[0].messages[-1].content))
    assert data["relationships"][0]["id"] == "REL-01"
    assert data["relationships"][0]["parent"] == "ENT-01"
    assert data["relationships"][0]["child"] == "ENT-02"
    assert [a["name"] for a in data["entities"][1]["attributes"]] == ["입고코드"]
