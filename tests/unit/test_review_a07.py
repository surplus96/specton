"""TC-A07: A07 비기능 요구 검토 관점 (설정형 리뷰어로 실행).

판단 자체는 LLM이 하므로 여기서는 관점 설정이 프롬프트에 들어가는지, 지적이 공통 Finding으로
기록되는지, 형식·근거가 틀린 응답을 거절하는지를 고정 응답으로 확인한다.
"""

import json

from specton.config import Settings
from specton.contracts import DesignState, Entity, FindingDraft, Function, Requirement
from specton.llm.stub import reply, stub_client
from specton.nodes.common import unwrap_data
from specton.review.perspective import PERSPECTIVES_DIR, load_perspective, load_perspectives
from specton.review.reviewer import ReviewOutput, review_perspective

A07 = load_perspective(PERSPECTIVES_DIR / "A07.yaml")

ACCESS_TEXT = (
    "보전 담당자는 접수·계획·배정을, 기술자는 본인에게 배정된 작업의 수행 결과를, "
    "승인 담당자는 검토·종료를 수행한다."
)


def _state() -> DesignState:
    """역할 속성은 있지만 역할별 허용 작업을 책임지는 기능이 없는 설계."""
    access = Requirement(
        id="REQ-01",
        source_ref={"kind": "xlsx", "sheet": "requirements", "row": 22},
        text=ACCESS_TEXT,
        original_text=ACCESS_TEXT,
        type="NFR",
        nfr_category="security",
        analysis_version=1,
    )
    work_order = Entity(
        id="ENT-01",
        pack="maintenance",
        name="보전 작업",
        description="보전 작업과 담당자",
        attributes=[
            {
                "id": "ATTR-01",
                "name": "작업번호",
                "data_type": "varchar",
                "length": 20,
                "is_key": True,
                "nullable": False,
                "req_ids": ["REQ-01"],
            },
            {
                "id": "ATTR-02",
                "name": "담당역할코드",
                "data_type": "char",
                "length": 2,
                "req_ids": ["REQ-01"],
            },
        ],
        req_ids=["REQ-01"],
    )
    manage = Function(
        id="FUNC-01",
        name="작업 관리",
        description="보전 작업을 등록·조회·수정한다",
        req_ids=["REQ-01"],
    )
    return DesignState(
        run_id="run-1", requirements=[access], functions=[manage], entities=[work_order]
    )


def _access_finding() -> FindingDraft:
    return FindingDraft(
        kind="access_control_unassigned",
        severity="major",
        targets=[{"kind": "function", "id": "FUNC-01"}],
        evidence=[{"req_id": "REQ-01", "quote": "기술자는 본인에게 배정된 작업의 수행 결과를"}],
        suggestion="역할별 허용 작업을 검사하는 책임을 작업 관리 기능 설명에 적는다",
        target_stage="functions",
    )


def _settings() -> Settings:
    return Settings(_env_file=None)


# 관점 설정


def test_a07_reads_requirements_functions_and_entities() -> None:
    assert set(A07.inputs) == {"requirements", "functions", "entities"}
    assert A07.prompt_version == "a07-v1"


def test_a07_is_loaded_with_the_other_perspectives() -> None:
    assert "A07" in [p.reviewer_id for p in load_perspectives()]


def test_a07_checklist_covers_access_audit_and_retention() -> None:
    checklist = " ".join(A07.checklist)

    for topic in ("권한", "감사", "변경 이력", "보존", "사용 중지", "원자성"):
        assert topic in checklist, topic


def test_a07_does_not_accept_a_column_as_proof_of_security() -> None:
    assert "속성이 있다는 사실만으로 요구가 충족됐다고 판단하지 않는다" in A07.instructions


def test_a07_separates_work_handled_outside_the_database() -> None:
    guards = " ".join(A07.false_positive_guards)

    assert "DB 밖" in A07.instructions
    assert "저장 속성이 없다는 이유만으로 지적하지 않는다" in guards
    assert "사내 체계에 맡긴 것은 지적하지 않는다" in guards
    for stage in ("functions", "data_model", "requirements"):
        assert stage in A07.instructions, stage


def test_a07_prompt_and_data_reach_the_review_model() -> None:
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    review_perspective(client, A07, _state(), _settings())

    (request,) = transport.sent
    system, user = request.messages
    assert (request.stage, request.prompt_version) == ("A07", "a07-v1")
    assert "속성이 있다는 사실만으로" in system.content
    assert "사내 체계에 맡긴 것은 지적하지 않는다" in system.content
    sent = json.loads(unwrap_data(user.content))
    assert set(sent) == {"requirements", "functions", "entities"}


# 정상 응답


def test_a07_reports_access_rule_without_responsible_function() -> None:
    client, _ = stub_client(reply(ReviewOutput(findings=(_access_finding(),))))

    run = review_perspective(client, A07, _state(), _settings())

    (result,) = run.results
    (finding,) = result.findings
    assert (result.ok, finding.reviewer_id, finding.source) == (True, "A07", "llm")
    assert (finding.target_stage, finding.targets[0].id) == ("functions", "FUNC-01")


def test_a07_no_findings_is_a_successful_review() -> None:
    client, _ = stub_client(reply(ReviewOutput(findings=())))

    run = review_perspective(client, A07, _state(), _settings())

    assert run.complete
    assert run.results[0].findings == ()


# 계약 오류·근거 부족


def test_a07_retries_when_output_breaks_the_contract() -> None:
    client, transport = stub_client(reply('{"findings": "없음"}'), reply(ReviewOutput(findings=())))

    run = review_perspective(client, A07, _state(), _settings())

    assert len(transport.sent) == 2
    assert run.results[0].ok


def test_a07_finding_without_evidence_is_rejected() -> None:
    no_evidence = _access_finding().model_dump(mode="json") | {"evidence": []}
    bad = json.dumps({"findings": [no_evidence]}, ensure_ascii=False)
    client, _ = stub_client(reply(bad), reply(bad), reply(bad))

    run = review_perspective(client, A07, _state(), _settings())

    assert (run.results[0].ok, run.results[0].error_code) == (False, "LLM_OUTPUT_INVALID")
    assert not run.complete


def test_a07_rejects_a_standalone_relationship_stage() -> None:
    wrong_stage = _access_finding().model_dump(mode="json") | {"target_stage": "relationships"}
    bad = json.dumps({"findings": [wrong_stage]}, ensure_ascii=False)
    client, transport = stub_client(reply(bad), reply(ReviewOutput(findings=())))

    review_perspective(client, A07, _state(), _settings())

    assert len(transport.sent) == 2
