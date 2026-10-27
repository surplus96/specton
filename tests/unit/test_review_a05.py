"""TC-A05: A05 관계 모순 검토 관점 (설정형 리뷰어로 실행)."""

import json

from specton.config import Settings
from specton.contracts import DesignState, Entity, FindingDraft, Relationship, Requirement
from specton.llm.stub import reply, stub_client
from specton.review.perspective import PERSPECTIVES_DIR, load_perspective
from specton.review.reviewer import ReviewOutput, review_perspective

A05 = load_perspective(PERSPECTIVES_DIR / "A05.yaml")


def _state() -> DesignState:
    req = Requirement(
        id="REQ-01",
        source_ref={"kind": "csv", "row": 2},
        text="한 설비는 상위 설비를 최대 하나 가질 수 있다",
        original_text="한 설비는 상위 설비를 최대 하나 가질 수 있다",
        type="FR",
        analysis_version=1,
    )
    equipment = Entity(
        id="ENT-01",
        pack="maintenance",
        name="설비",
        description="설비 대장",
        attributes=[
            {
                "id": "ATTR-01",
                "name": "설비코드",
                "data_type": "varchar",
                "length": 20,
                "req_ids": ["REQ-01"],
            }
        ],
        req_ids=["REQ-01"],
    )
    hierarchy = Relationship(
        id="REL-01",
        parent="ENT-01",
        child="ENT-01",
        cardinality="N:M",
        optional=True,
        rationale="상위·하위 설비",
        req_ids=["REQ-01"],
    )
    return DesignState(
        run_id="run-1", requirements=[req], entities=[equipment], relationships=[hierarchy]
    )


def _cardinality_finding() -> FindingDraft:
    return FindingDraft(
        kind="cardinality_conflict",
        severity="major",
        targets=[{"kind": "relationship", "id": "REL-01"}],
        evidence=[{"req_id": "REQ-01", "quote": "상위 설비를 최대 하나 가질 수 있다"}],
        suggestion="상위 설비 관계를 1:N 자기참조로 바꾼다",
        target_stage="data_model",
    )


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_a05_reads_relationships_with_their_requirements() -> None:
    assert set(A05.inputs) == {"requirements", "entities", "relationships"}
    assert A05.prompt_version == "a05-v1"


def test_a05_prompt_keeps_the_alternative_expression_guard() -> None:
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    review_perspective(client, A05, _state(), _settings())

    system = transport.sent[0].messages[0].content
    assert "같은 요구를 충족하는 다른 관계 표현" in system


def test_a05_checklist_covers_relationship_conflicts() -> None:
    checklist = " ".join(A05.checklist)

    for topic in ("카디널리티", "방향", "필수", "자기참조", "N:M", "식별"):
        assert topic in checklist, topic
    assert "data_model" in A05.instructions


def test_a05_reports_a_cardinality_conflict() -> None:
    client, _ = stub_client(reply(ReviewOutput(findings=(_cardinality_finding(),))))

    run = review_perspective(client, A05, _state(), _settings())

    (result,) = run.results
    (finding,) = result.findings
    assert (result.ok, finding.reviewer_id, finding.target_stage) == (True, "A05", "data_model")
    assert finding.targets[0].id == "REL-01"


def test_a05_retries_when_output_breaks_the_contract() -> None:
    client, transport = stub_client(reply("{}"), reply(ReviewOutput(findings=())))

    run = review_perspective(client, A05, _state(), _settings())

    assert len(transport.sent) == 2
    assert run.results[0].ok


def test_a05_finding_without_evidence_is_rejected() -> None:
    no_evidence = _cardinality_finding().model_dump(mode="json") | {"evidence": []}
    bad = json.dumps({"findings": [no_evidence]}, ensure_ascii=False)
    client, _ = stub_client(reply(bad), reply(bad), reply(bad))

    run = review_perspective(client, A05, _state(), _settings())

    assert (run.results[0].ok, run.results[0].error_code) == (False, "LLM_OUTPUT_INVALID")
