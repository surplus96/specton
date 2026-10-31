"""TC-A08: A08 정규화 검토 관점 (설정형 리뷰어로 실행)."""

import json

from specton.config import Settings
from specton.contracts import DesignState, Entity, FindingDraft, Requirement
from specton.llm.stub import refusal, reply, stub_client
from specton.packs.examples import load_examples
from specton.review.perspective import PERSPECTIVES_DIR, load_perspective, load_perspectives
from specton.review.reviewer import ReviewOutput, review_perspective

A08 = load_perspective(PERSPECTIVES_DIR / "A08.yaml")

DOC_TEXT = "하나의 수불 문서에는 하나 이상의 품목 내역을 등록한다."
SNAPSHOT_TEXT = "확정한 거래는 거래 당시의 품목명을 그대로 보존해야 한다."


def _requirement(text: str) -> Requirement:
    return Requirement(
        id="REQ-01",
        source_ref={"kind": "csv", "row": 2},
        text=text,
        original_text=text,
        type="FR",
        analysis_version=1,
    )


def _attribute(attr_id: str, name: str, **extra: object) -> dict[str, object]:
    return {
        "id": attr_id,
        "name": name,
        "data_type": "varchar",
        "length": 100,
        "req_ids": ["REQ-01"],
        **extra,
    }


def _entity(name: str, *attributes: dict[str, object]) -> Entity:
    return Entity(
        id="ENT-01",
        pack="inventory",
        name=name,
        description=f"{name} 엔티티",
        attributes=list(attributes),
        req_ids=["REQ-01"],
    )


def _state() -> DesignState:
    """수불문서가 품목 코드 여러 개를 한 칸에 담는 설계."""
    document = _entity(
        "수불문서",
        _attribute("ATTR-01", "문서번호", is_key=True, nullable=False),
        _attribute("ATTR-02", "품목코드목록"),
    )
    return DesignState(run_id="run-1", requirements=[_requirement(DOC_TEXT)], entities=[document])


def _snapshot_state() -> DesignState:
    """거래 당시 품목명을 보존하라는 요구가 있고 내역이 품목명을 저장하는 설계."""
    line = _entity(
        "수불내역",
        _attribute("ATTR-01", "품목코드", is_key=True, nullable=False),
        _attribute("ATTR-02", "품목명", description="거래 당시 품목명"),
    )
    return DesignState(run_id="run-1", requirements=[_requirement(SNAPSHOT_TEXT)], entities=[line])


def _no_basis_state() -> DesignState:
    """품목명을 다시 저장하지만 보존 요구도, 품목 엔티티도 입력에 없는 설계."""
    line = _entity(
        "수불내역",
        _attribute("ATTR-01", "품목코드", is_key=True, nullable=False),
        _attribute("ATTR-02", "품목명"),
    )
    return DesignState(
        run_id="run-1", requirements=[_requirement("각 내역은 한 품목을 가진다.")], entities=[line]
    )


def _multi_value_finding() -> FindingDraft:
    return FindingDraft(
        kind="multi_valued_attribute",
        severity="major",
        targets=[{"kind": "attribute", "id": "ATTR-02"}],
        evidence=[{"req_id": "REQ-01", "quote": DOC_TEXT}],
        suggestion="내역마다 한 행을 두는 별도 엔티티로 나눈다",
        target_stage="data_model",
    )


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_a08_reads_requirements_and_entities_only() -> None:
    assert set(A08.inputs) == {"requirements", "entities"}
    assert A08.prompt_version == "a08-v1"
    assert "A08" in [p.reviewer_id for p in load_perspectives()]


def test_a08_sends_the_snapshot_requirement_with_its_guard() -> None:
    """거래 당시 값 보존 요구와 중복 속성이 함께 전달되고 면제 지침이 프롬프트에 있다.

    stub의 빈 응답은 실제 LLM이 오탐을 피한다는 증거가 아니다. 입력 전달만 고정한다.
    """
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    run = review_perspective(client, A08, _snapshot_state(), _settings())

    request = transport.sent[0]
    sent = json.dumps(request.messages[-1].content, ensure_ascii=False)
    assert SNAPSHOT_TEXT in sent and "거래 당시 품목명" in sent
    assert "스냅샷·이력 저장" in request.messages[0].content
    assert run.results[0].ok


def test_a08_guard_does_not_treat_missing_preservation_as_duplication() -> None:
    """보존 요구도 다른 엔티티도 입력에 없는 사례. 삭제를 권하지 않는 지침이 프롬프트에 있다."""
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    review_perspective(client, A08, _no_basis_state(), _settings())

    request = transport.sent[0]
    sent = json.dumps(request.messages[-1].content, ensure_ascii=False)
    assert "보존" not in sent
    assert "삭제를 권하지 않는다" in request.messages[0].content


def test_a08_checklist_covers_normalization_problems() -> None:
    checklist = " ".join(A08.checklist)

    for topic in ("여러 값", "반복", "다시 저장", "서로를 결정", "계산"):
        assert topic in checklist, topic
    assert "data_model" in A08.instructions


def test_a08_sends_attributes_to_the_reviewer() -> None:
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    review_perspective(client, A08, _state(), _settings())

    sent = json.dumps(transport.sent[0].messages[-1].content, ensure_ascii=False)
    assert "품목코드목록" in sent


def test_a08_reports_a_multi_valued_attribute() -> None:
    client, _ = stub_client(reply(ReviewOutput(findings=(_multi_value_finding(),))))

    run = review_perspective(client, A08, _state(), _settings())

    (result,) = run.results
    (finding,) = result.findings
    assert (result.ok, finding.reviewer_id, finding.target_stage) == (True, "A08", "data_model")
    assert finding.targets[0].id == "ATTR-02"


def test_a08_accepts_a_design_without_findings() -> None:
    client, _ = stub_client(reply(ReviewOutput(findings=())))

    run = review_perspective(client, A08, _state(), _settings())

    assert (run.results[0].ok, run.results[0].findings) == (True, ())


def test_a08_retries_when_output_breaks_the_contract() -> None:
    client, transport = stub_client(reply("{}"), reply(ReviewOutput(findings=())))

    run = review_perspective(client, A08, _state(), _settings())

    assert len(transport.sent) == 2
    assert run.results[0].ok


def test_a08_finding_without_evidence_is_rejected() -> None:
    no_evidence = _multi_value_finding().model_dump(mode="json") | {"evidence": []}
    bad = json.dumps({"findings": [no_evidence]}, ensure_ascii=False)
    client, _ = stub_client(reply(bad), reply(bad), reply(bad))

    run = review_perspective(client, A08, _state(), _settings())

    assert (run.results[0].ok, run.results[0].error_code) == (False, "LLM_OUTPUT_INVALID")


def test_a08_refusal_fails_the_branch_without_retrying() -> None:
    client, transport = stub_client(refusal())

    run = review_perspective(client, A08, _state(), _settings())

    assert len(transport.sent) == 1
    assert (run.results[0].ok, run.results[0].error_code) == (False, "LLM_REFUSED")
    assert not run.complete


def test_maintenance_examples_separate_multi_value_from_recorded_values() -> None:
    """MNT-004는 다중값 지적, MNT-015는 요구사항이 남기라고 한 값이라 지적이 없다."""
    multi_value, recorded = load_examples("maintenance", "A08", ReviewOutput)

    assert multi_value.source_id == "MNT-004"
    assert [f.kind for f in multi_value.output.findings] == ["multi_valued_attribute"]
    assert recorded.source_id == "MNT-015"
    assert recorded.output.findings == ()
    assert "부품명" in [a["name"] for a in recorded.input["entities"][0]["attributes"]]
