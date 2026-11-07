"""TC-A08: A08 정규화 검토 관점 (설정형 리뷰어로 실행).

A08은 요구사항·엔티티와 함께 A04 관계와 모델 정리 결과 요약을 받는다 (#12). 그래서 검토할 상태는
정리 결과를 담아야 한다. 정리는 실제 코드로 하고, 실제 팩에 아직 없는 단어는 테스트용 사전을 쓴다.
"""

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest
import yaml

from specton.codegen.model import Normalized
from specton.codegen.naming import NamingRules, TermInfo
from specton.codegen.normalize import PackRef, normalize
from specton.config import Settings
from specton.contracts import DesignState, Entity, FindingDraft, Relationship, Requirement
from specton.llm.stub import refusal, reply, stub_client
from specton.packs.examples import load_examples
from specton.review.normalized_view import normalized_view
from specton.review.perspective import PERSPECTIVES_DIR, load_perspective, load_perspectives
from specton.review.reviewer import (
    CombinedReviewOutput,
    ReviewOutput,
    review_combined,
    review_perspective,
)

A08 = load_perspective(PERSPECTIVES_DIR / "A08.yaml")

DOC_TEXT = "하나의 수불 문서에는 하나 이상의 품목 내역을 등록한다."
SNAPSHOT_TEXT = "확정한 거래는 거래 당시의 품목명을 그대로 보존해야 한다."


def _requirement(text: str) -> Requirement:
    return Requirement(
        id="REQ-01",
        source_ref={"file_format": "csv", "row": 2},
        text=text,
        draft_text=text,
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


class _Words:
    """테스트용 사전. 이 이름들은 실제 팩 사전에 아직 없거나 예시용 가상 이름이다 (#12 계획 3-3)."""

    digest = "a08-test"
    words: ClassVar[dict[str, str]] = {
        "수불문서": "SBL_DOC",
        "문서번호": "DOC_NO",
        "품목코드목록": "ITEM_CD_LIST",
        "품목": "ITEM",
        "품목코드": "ITEM_CD",
        "품목명": "ITEM_NM",
        "수불내역": "SBL_DSCTN",
        "내역순번": "DSCTN_SN",
        "수량": "QTY",
        "기술자": "ENGNR",
        "기술자코드": "ENGNR_CD",
        "기술자명": "ENGNR_NM",
        "소속팀코드목록": "TEAM_CD_LIST",
        "보전작업": "MNTN_JOB",
        "작업번호": "JOB_NO",
        "부품": "PRTS",
        "부품코드": "PRTS_CD",
        "부품명": "PRTS_NM",
        "단위명": "UNIT_NM",
        "사용부품실적": "USE_PRTS_RSLT",
        "사용수량": "USE_QTY",
        "적용단가": "APLCN_UNTPRC",
        "사용일시": "USE_DT",
        "기록자식별값": "RCDR_IDNTF_VL",
    }

    def term(self, logical_name: str) -> TermInfo | None:
        return None

    def compose(self, logical_name: str) -> str | None:
        return self.words.get(logical_name)


_RULES = NamingRules(max_bytes=63, reserved_words=frozenset())


def _normalized(state: DesignState, pack: str = "inventory") -> DesignState:
    """그래프의 정리 노드처럼 정리 결과를 상태에 담는다."""
    result = normalize(state, pack=PackRef(pack, "test"), lexicon=_Words(), rules=_RULES)
    assert isinstance(result, Normalized), result
    return state.evolve(normalized=result.model)


def _state() -> DesignState:
    """수불문서가 품목 코드 여러 개를 한 칸에 담는 설계."""
    document = _entity(
        "수불문서",
        _attribute("ATTR-01", "문서번호", is_key=True, nullable=False),
        _attribute("ATTR-02", "품목코드목록"),
    )
    return _normalized(
        DesignState(run_id="run-1", requirements=[_requirement(DOC_TEXT)], entities=[document])
    )


def _snapshot_state() -> DesignState:
    """거래 당시 품목명을 보존하라는 요구가 있고 내역이 품목명을 저장하는 설계."""
    line = _entity(
        "수불내역",
        _attribute("ATTR-01", "품목코드", is_key=True, nullable=False),
        _attribute("ATTR-02", "품목명", description="거래 당시 품목명"),
    )
    return _normalized(
        DesignState(run_id="run-1", requirements=[_requirement(SNAPSHOT_TEXT)], entities=[line])
    )


def _no_basis_state() -> DesignState:
    """품목명을 다시 저장하지만 보존 요구도, 품목 엔티티도 입력에 없는 설계."""
    line = _entity(
        "수불내역",
        _attribute("ATTR-01", "품목코드", is_key=True, nullable=False),
        _attribute("ATTR-02", "품목명"),
    )
    return _normalized(
        DesignState(
            run_id="run-1",
            requirements=[_requirement("각 내역은 한 품목을 가진다.")],
            entities=[line],
        )
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


def test_a08_reads_relationships_and_the_normalized_result() -> None:
    assert A08.inputs == ("requirements", "entities", "relationships", "normalized")
    assert A08.prompt_version == "a08-v2"
    # 정리 결과의 테이블·컬럼 ID는 구조 연결용이고 지적 대상은 원래 ID라는 안내
    assert "엔티티·속성·관계 ID" in A08.instructions
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


def test_maintenance_examples_keep_only_the_multi_value_finding() -> None:
    """MNT-004는 다중값 지적이다. MNT-015는 실행용 예시에서 뺐다 (#12 계획 4절).

    기대 결과가 확정되지 않은 예시를 남기면 YAML 주석과 달리 LLM에는 "지적 없음" 답으로 전달된다.
    """
    examples = load_examples("maintenance", "A08", ReviewOutput)

    assert [e.source_id for e in examples] == ["MNT-004"]
    assert [f.kind for f in examples[0].output.findings] == ["multi_valued_attribute"]


# ── 미확정 MNT-015: 실행용 예시 밖의 시험 자료 (#12) ─────────────────

PENDING_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "a08_mnt015_pending.yaml"
PENDING_TEXT = "작업에는 사용한 부품의"  # MNT-015 요구 문장 앞부분


def _maintenance_state() -> DesignState:
    """MNT-015 설계 구조를 정리한 상태. 프롬프트에 그 예시가 섞이는지 보려고 쓴다."""
    pending = yaml.safe_load(PENDING_FIXTURE.read_text(encoding="utf-8"))
    return _normalized(_example_state(pending["input"]), "maintenance")


def test_pending_mnt015_structure_matches_the_real_normalization() -> None:
    """원문 확인 전 보관한 구조. 부모 키는 관계에서 오고, 실적이 부품명·단위명을 따로 남긴다."""
    pending = yaml.safe_load(PENDING_FIXTURE.read_text(encoding="utf-8"))
    assert (pending["source_id"], "output" in pending) == ("MNT-015", False)  # 기대 결과 없음
    state = _normalized(_example_state(pending["input"]), pending["pack"])
    assert state.normalized is not None
    assert pending["input"]["normalized"] == normalized_view(state.normalized)
    names = {e["name"]: [a["name"] for a in e["attributes"]] for e in pending["input"]["entities"]}
    assert {"부품명", "단위명"} <= set(names["부품"]) & set(names["사용부품실적"])


def test_parallel_prompt_does_not_carry_the_pending_example() -> None:
    client, transport = stub_client(reply(ReviewOutput(findings=())))

    review_perspective(client, A08, _maintenance_state(), _settings(), pack="maintenance")

    *examples, data = transport.sent[0].messages
    assert all(PENDING_TEXT not in m.content for m in examples)  # 예시 대화 쌍에 없음
    assert "소속팀코드목록" in " ".join(m.content for m in examples)  # MNT-004 예시는 들어감
    assert PENDING_TEXT in data.content  # 검토할 실제 입력에는 있다


def test_combined_prompt_does_not_carry_the_pending_example_in_the_a08_block() -> None:
    perspectives = load_perspectives()
    output = CombinedReviewOutput.model_validate(
        {"perspectives": [{"reviewer_id": p.reviewer_id, "findings": []} for p in perspectives]}
    )
    client, transport = stub_client(reply(output))

    review_combined(client, perspectives, _maintenance_state(), _settings(), pack="maintenance")

    system = transport.sent[0].messages[0].content
    a08_block = system[system.index("## A08") :]
    assert "소속팀코드목록" in a08_block
    assert PENDING_TEXT not in a08_block


# ── 예시 검증 (#12) ──────────────────────────────────────────────────


def _example_state(example_input: dict[str, Any]) -> DesignState:
    return DesignState(
        run_id="example",
        requirements=[
            Requirement(
                id=r["id"],
                source_ref={"file_format": "csv", "row": 2},
                text=r["text"],
                draft_text=r["text"],
                type=r["type"],
                nfr_category=r["nfr_category"],
                analysis_version=1,
            )
            for r in example_input["requirements"]
        ],
        entities=[Entity.model_validate(e) for e in example_input["entities"]],
        relationships=[Relationship.model_validate(r) for r in example_input["relationships"]],
    )


_EXAMPLES = [
    (pack, n, example)
    for pack in ("inventory", "maintenance")
    for n, example in enumerate(load_examples(pack, "A08", ReviewOutput))
]


@pytest.mark.parametrize(
    ("pack", "example"),
    [pytest.param(pack, ex, id=f"{pack}-{n}-{ex.source_id}") for pack, n, ex in _EXAMPLES],
)
def test_example_input_matches_the_real_normalization(pack: str, example: Any) -> None:
    """예시의 normalized 블록은 손으로 쓴 값이 아니라 정리 코드 결과와 같아야 한다."""
    assert list(example.input) == ["requirements", "entities", "relationships", "normalized"]
    state = _normalized(_example_state(example.input), pack)
    assert state.normalized is not None
    assert example.input["normalized"] == normalized_view(state.normalized)


@pytest.mark.parametrize(
    ("pack", "example"),
    [pytest.param(pack, ex, id=f"{pack}-{n}-{ex.source_id}") for pack, n, ex in _EXAMPLES],
)
def test_example_does_not_put_parent_keys_in_child_attributes(pack: str, example: Any) -> None:
    """부모 키는 A03 속성이 아니라 관계에서 파생된다. 예시도 실제 흐름과 같은 모양이다."""
    view = example.input["normalized"]
    attribute_names = {
        e["id"]: {a["name"] for a in e["attributes"]} for e in example.input["entities"]
    }
    for table in view["tables"]:
        inherited = {c["name"] for c in table["columns"] if "relationship_id" in c}
        assert not inherited & attribute_names[table["entity_id"]], table["name"]


def test_inventory_line_example_shows_the_inherited_key_in_its_primary_key() -> None:
    """수불내역 PK = 문서번호(식별 관계 REL-01에서 옴) + 내역순번(자기 키)."""
    _, line_example = load_examples("inventory", "A08", ReviewOutput)
    [line] = [t for t in line_example.input["normalized"]["tables"] if t["name"] == "수불내역"]
    by_id = {c["id"]: c for c in line["columns"]}
    assert [
        (by_id[c]["name"], by_id[c].get("relationship_id") or by_id[c].get("attribute_id"))
        for c in line["primary_key"]
    ] == [("문서번호", "REL-01"), ("내역순번", "ATTR-03")]
    assert line_example.output.findings == ()
