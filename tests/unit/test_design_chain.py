"""설계 노드 연속 호출. 앞 단계의 실제 반환값을 상태에 넣어 다음 단계에 넘긴다.

두 갈래로 나뉜다.
- A02 → A03 → A04 → 모델 정리(#12) → A08: A04까지의 실제 반환값을 정리하고, 그 정리 결과를
  A08 입력(`relationships`·`normalized`)으로 넘긴다 (#12 A08 재확인).
- A04 → 모델 정리: 실제 팩 사전으로 정리했을 때의 결과와, 테스트용 단어를 보탠 결과.

노드 사이의 데이터 연결만 고정 응답(stub)으로 확인한다. 실제 LLM의 품질이나 그래프(#17) 전체
실행을 검증하지 않는다. 고정 응답은 maintenance 예시와 이 파일의 값이지만, 각 단계의 입력 상태는
앞 단계 반환값으로만 만든다.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

import pytest

from specton.codegen.model import Normalized
from specton.codegen.naming import (
    DEFAULT_PACK_ROOT,
    PackLexicon,
    load_naming_rules,
    load_pack_lexicon,
)
from specton.codegen.normalize import PackRef, normalize
from specton.codegen.normalize_step import normalize_from_state
from specton.config import Settings
from specton.contracts import DesignState, FindingDraft, Function, Relationship, Requirement
from specton.contracts.state import VersionInfo, find_trace_issues
from specton.llm.stub import reply, stub_client
from specton.nodes import a02_functions, a03_entities, a04_relationships
from specton.nodes.a02_functions import A02Output
from specton.nodes.a03_entities import A03Output, A03Result
from specton.nodes.a04_relationships import A04Output
from specton.nodes.common import unwrap_data
from specton.packs.build import read_yaml
from specton.packs.examples import load_examples
from specton.review.merge import merge_review
from specton.review.normalized_view import normalized_view
from specton.review.perspective import PERSPECTIVES_DIR, load_perspective
from specton.review.reviewer import (
    MissingReviewInput,
    ReviewOutput,
    ReviewRun,
    review_perspective,
)

PACK = "maintenance"
A08 = load_perspective(PERSPECTIVES_DIR / "A08.yaml")
REPORTER_QUOTE = "신고자 사내 식별값"


def _settings() -> Settings:
    return Settings(_env_file=None)


def _a02_output() -> A02Output:
    [example] = load_examples(PACK, "A02", A02Output)
    return example.output


def _a03_output() -> A03Output:
    [example] = load_examples(PACK, "A03", A03Output)
    return example.output


def _a04_output() -> A04Output:
    """이 사례의 A04 예시가 없어 A02 예시와 같은 요구사항 문장을 인용해 적는다."""

    def relationship(parent: str, child: str, quote: str, req_id: str) -> dict[str, Any]:
        return {
            "parent_name": parent,
            "child_name": child,
            "cardinality": "1:N",
            "optional": False,
            "rationale": f'"{quote}"',
            "req_ids": [req_id],
        }

    return A04Output.model_validate(
        {
            "relationships": [
                relationship("설비", "고장접수", "한 접수는 한 설비에 대한 것이며", "REQ-01"),
                relationship(
                    "고장접수", "보전작업", "하나 이상의 보전 작업으로 나누어 처리할 수", "REQ-01"
                ),
                relationship("팀", "보전작업", "작업은 한 팀과 최대 한 기술자에게", "REQ-02"),
            ]
        }
    )


def _requirements_state() -> DesignState:
    """요구사항만 있는 상태. 나머지는 각 노드의 run()이 만든다."""
    [example] = load_examples(PACK, "A02", A02Output)
    requirements = tuple(
        Requirement(
            id=r["id"],
            source_ref={"file_format": "csv", "row": n + 2},
            text=r["text"],
            draft_text=r["text"],
            type=r["type"],
            nfr_category=r["nfr_category"],
            analysis_version=1,
        )
        for n, r in enumerate(example.input["requirements"])
    )
    return DesignState(run_id="run-1", requirements=requirements)


@dataclass(frozen=True)
class _Chain:
    """각 단계의 실제 반환값과 그것을 차례로 반영한 최종 상태."""

    functions: tuple[Function, ...]
    design: A03Result
    relationships: tuple[Relationship, ...]
    state: DesignState
    sent: list[Any]


def _run_design() -> _Chain:
    settings = _settings()
    client, transport = stub_client(
        reply(_a02_output()), reply(_a03_output()), reply(_a04_output())
    )

    state = _requirements_state()
    functions = a02_functions.run(client, state, settings, pack=PACK).output
    state = state.evolve(functions=functions)
    design = a03_entities.run(client, state, settings, pack=PACK).output
    state = state.evolve(entities=design.entities, functions=design.functions)
    relationships = a04_relationships.run(client, state, settings, pack=PACK).output
    state = state.evolve(relationships=relationships)
    return _Chain(functions, design, relationships, state, transport.sent)


def _review(state: DesignState, *findings: FindingDraft) -> tuple[ReviewRun, list[Any]]:
    client, transport = stub_client(reply(ReviewOutput(findings=findings)))
    run = review_perspective(client, A08, state, _settings(), pack=PACK)
    return run, transport.sent


def _attribute_id(state: DesignState, entity: str, attribute: str) -> str:
    [found] = [e for e in state.entities if e.name == entity]
    [target] = [a for a in found.attributes if a.name == attribute]
    return target.id


def _finding(
    target_id: str, quote: str = REPORTER_QUOTE, targets: list[dict[str, str]] | None = None
) -> FindingDraft:
    """근거 연결만 본다. 지적 내용이 맞는 판단인지는 stub으로 알 수 없다."""
    return FindingDraft(
        kind="duplicated_fact",
        severity="major",
        targets=targets or [{"kind": "attribute", "id": target_id}],
        evidence=[{"req_id": "REQ-01", "quote": quote}],
        suggestion="신고자 정보를 한 곳에만 둔다",
        target_stage="data_model",
    )


def _data(request: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(unwrap_data(request.messages[-1].content))
    return data


def test_each_stage_uses_what_the_previous_stage_returned() -> None:
    chain = _run_design()

    assert [r.stage for r in chain.sent] == ["A02", "A03", "A04"]
    # A02가 코드로 붙인 기능 ID가 A03 요청에 그대로 가고, 끝까지 유지된다
    function_ids = [f.id for f in chain.functions]
    assert function_ids == ["FUNC-01", "FUNC-02"]
    assert [f["id"] for f in _data(chain.sent[1])["functions"]] == function_ids
    assert [f.id for f in chain.state.functions] == function_ids
    # A03이 엔티티·속성에 ID를 붙이고, A04 요청은 그 엔티티를 받는다
    entities = {e.name: e for e in chain.design.entities}
    assert all(re.fullmatch(r"ENT-[0-9a-f]{16}", e.id) for e in entities.values())
    assert all(
        re.fullmatch(r"ATTR-[0-9a-f]{16}", a.id) for e in entities.values() for a in e.attributes
    )
    assert [e["name"] for e in _data(chain.sent[2])["entities"]] == list(entities)
    assert chain.state.entities == chain.design.entities
    # A04 관계는 A03이 만든 엔티티 ID를 가리킨다
    assert [(r.parent, r.child) for r in chain.relationships] == [
        (entities["설비"].id, entities["고장접수"].id),
        (entities["고장접수"].id, entities["보전작업"].id),
        (entities["팀"].id, entities["보전작업"].id),
    ]


def test_entity_ops_point_at_the_entities_a03_returned() -> None:
    chain = _run_design()
    entities = {e.name: e for e in chain.design.entities}

    def ops(function: Function) -> dict[str, list[str]]:
        return {op.entity_id: sorted(c.value for c in op.operations) for op in function.entity_ops}

    reception, assignment = chain.state.functions
    assert ops(reception) == {
        entities["설비"].id: ["R"],
        entities["고장접수"].id: ["C", "R", "U"],
        entities["보전작업"].id: ["C"],
        entities["변경이력"].id: ["C"],
    }
    assert ops(assignment) == {
        entities["보전작업"].id: ["R", "U"],
        entities["팀"].id: ["R"],
        entities["기술자"].id: ["R"],
        entities["변경이력"].id: ["C"],
    }


def test_final_state_keeps_function_fields_and_has_no_trace_issues() -> None:
    chain = _run_design()

    assert find_trace_issues(chain.state) == []
    assert [f.model_dump(exclude={"entity_ops"}) for f in chain.state.functions] == [
        f.model_dump(exclude={"entity_ops"}) for f in chain.functions
    ]


def test_a03_retries_a_function_id_that_a02_did_not_return() -> None:
    """A03 출력은 A02 반환값을 기준으로 검사한다. 없는 기능 ID는 재요청한다."""
    settings = _settings()
    invalid = _a03_output().model_dump(mode="json")
    invalid["entity_ops"][0]["function_id"] = "FUNC-03"
    client, transport = stub_client(
        reply(_a02_output()),
        reply(json.dumps(invalid, ensure_ascii=False)),
        reply(_a03_output()),
    )
    state = _requirements_state()

    functions = a02_functions.run(client, state, settings, pack=PACK).output
    design = a03_entities.run(client, state.evolve(functions=functions), settings, pack=PACK).output

    assert [r.stage for r in transport.sent] == ["A02", "A03", "A03"]
    assert [f.id for f in design.functions] == [f.id for f in functions]


def test_a08_request_carries_the_chain_result_within_its_inputs() -> None:
    state = _reviewable_state()

    _, sent = _review(state)

    # A08은 요구사항·엔티티와 함께 A04 관계와 정리 결과 요약을 받는다 (#12)
    assert A08.inputs == ("requirements", "functions", "entities", "relationships", "normalized")
    data = _data(sent[0])
    assert list(data) == ["requirements", "functions", "entities", "relationships", "normalized"]
    assert data["requirements"] == [r.model_dump(mode="json") for r in state.requirements]
    assert data["entities"] == [e.model_dump(mode="json") for e in state.entities]
    assert data["relationships"] == [r.model_dump(mode="json") for r in state.relationships]
    assert state.normalized is not None
    assert data["normalized"] == normalized_view(state.normalized, include_fk_names=True)


def test_a08_sees_inherited_keys_with_their_source_relationship() -> None:
    """FK 칸은 엔티티 속성이 아니라 관계에서 온다. A08은 요약에서 그 출처 관계를 본다."""
    state = _reviewable_state()
    _, sent = _review(state)
    view = _data(sent[0])["normalized"]
    work_entity = next(e for e in state.entities if e.name == "보전작업")
    [work] = [t for t in view["tables"] if t.get("entity_id") == work_entity.id]
    from_relationships = {c["relationship_id"] for c in work["columns"] if "relationship_id" in c}
    # 고장접수 → 보전작업, 팀 → 보전작업 (A04 반환 순서 1·2번 관계)
    assert from_relationships == {state.relationships[1].id, state.relationships[2].id}
    assert {a.id for a in work_entity.attributes} == {
        c["attribute_id"] for c in work["columns"] if "attribute_id" in c
    }


def test_a08_without_normalized_result_stops_before_calling_the_llm() -> None:
    """정리 결과 없이 정상 검토처럼 처리하지 않는다 (#12 계획 2-4)."""
    client, transport = stub_client(reply(ReviewOutput(findings=())))
    with pytest.raises(MissingReviewInput):
        review_perspective(client, A08, _run_design().state, _settings(), pack=PACK)
    assert not transport.sent


def test_a08_finding_on_a_relationship_survives_and_table_ids_are_not_targets() -> None:
    """지적 대상은 원래 엔티티·속성·관계 ID다. 정리 결과의 테이블·컬럼 ID는 대상이 아니다."""
    state = _reviewable_state()
    assert state.normalized is not None
    rel = state.relationships[1]
    table_id = state.normalized.tables[0].id
    on_rel = _finding("", targets=[{"kind": "relationship", "id": rel.id}])
    on_table = _finding("", targets=[{"kind": "entity", "id": table_id}])

    run, _ = _review(state, on_rel, on_table)
    merged = merge_review(state, run.results, ("A08",))

    assert [f.targets[0].id for f in merged.findings] == [rel.id]
    assert [r.reason for r in merged.rejected] == ["unknown_target"]


def test_grounded_a08_finding_survives_the_common_merge() -> None:
    state = _reviewable_state()
    target_id = _attribute_id(state, "고장접수", "신고자식별값")

    run, _ = _review(state, _finding(target_id))
    merged = merge_review(state, run.results, ("A08",))

    assert (merged.complete, merged.rejected) == (True, ())
    (finding,) = merged.findings
    assert (finding.reviewer_id, finding.targets[0].id) == ("A08", target_id)
    assert finding.evidence[0].quote == REPORTER_QUOTE


def test_a08_finding_without_real_target_or_quote_is_rejected_by_the_common_merge() -> None:
    state = _reviewable_state()
    target_id = _attribute_id(state, "고장접수", "신고자식별값")
    findings = (
        _finding(target_id),
        _finding("ATTR-0000000000000000"),
        _finding(target_id, quote="요구사항에 없는 문장"),
    )

    run, _ = _review(state, *findings)
    merged = merge_review(state, run.results, ("A08",))

    assert [f.targets[0].id for f in merged.findings] == [target_id]
    assert sorted(r.reason for r in merged.rejected) == ["quote_not_found", "unknown_target"]


def test_a08_without_findings_is_a_complete_review() -> None:
    state = _reviewable_state()

    run, _ = _review(state)
    merged = merge_review(state, run.results, ("A08",))

    assert run.complete
    assert (merged.complete, merged.findings, merged.rejected) == (True, (), ())


def test_review_does_not_change_the_design_state() -> None:
    state = _reviewable_state()
    before = state.model_dump(mode="json")
    target_id = _attribute_id(state, "고장접수", "신고자식별값")

    run, _ = _review(state, _finding(target_id))
    merge_review(state, run.results, ("A08",))

    assert state.model_dump(mode="json") == before


# ── 모델 정리 (#12) ──────────────────────────────────────────────────
# A04까지의 실제 반환값을 그대로 정리에 넣는다. 그래프에서는 실행기가 첫 상태의 versions에
# 팩을 넣으므로(#121) 같은 값만 더한다. 중간 결과(엔티티·관계)는 바꾸지 않는다.

PACK_VERSION = str(read_yaml(DEFAULT_PACK_ROOT / PACK / "manifest.yaml")["version"])


def _with_pack(state: DesignState) -> DesignState:
    return state.evolve(versions=VersionInfo(pack_id=PACK, pack_version=PACK_VERSION))


def _test_lexicon() -> PackLexicon:
    """고정 공식 단어와 이음동의어를 포함한 실제 팩 사전."""
    return load_pack_lexicon(PACK)


def _reviewable_state() -> DesignState:
    """A04까지의 실제 반환값을 정리하고, 그 결과를 상태에 담는다(그래프의 정리 노드와 같은 위치)."""
    state = _with_pack(_run_design().state)
    result = normalize(
        state, pack=PackRef(PACK, PACK_VERSION), lexicon=_test_lexicon(), rules=load_naming_rules()
    )
    assert isinstance(result, Normalized), result
    return state.evolve(normalized=result.model)


def test_normalize_takes_the_chain_result_with_official_aliases() -> None:
    """실제 공식 이음동의어로 기존 설계가 입력 변형 없이 정리된다."""
    state = _with_pack(_run_design().state)
    before = state.model_dump(mode="json")

    result = normalize_from_state({"design": state})

    assert isinstance(result, Normalized)
    # 요구사항·기능(CRUD 포함)·엔티티·관계를 바꾸지 않는다
    assert state.model_dump(mode="json") == before


def test_normalize_derives_keys_from_the_chain_result_with_the_real_pack() -> None:
    """실제 팩 사전으로 테이블·PK·FK를 만들며 앞 단계 결과는 보존한다."""
    lexicon = _test_lexicon()
    state = _with_pack(_run_design().state)
    before = state.model_dump(mode="json")

    result = normalize(
        state, pack=PackRef(PACK, PACK_VERSION), lexicon=lexicon, rules=load_naming_rules()
    )

    assert isinstance(result, Normalized), result
    model = result.model
    entities = {e.name: e for e in state.entities}
    tables = {t.entity_id: t for t in model.tables}
    assert set(tables) == {e.id for e in state.entities}  # 엔티티마다 테이블 하나

    def fk_names(rel_index: int) -> list[str]:
        rel = state.relationships[rel_index]
        (fk,) = [f for f in model.foreign_keys if f.relationship_id == rel.id]
        child = tables[rel.child]
        assert fk.parent_columns == tables[rel.parent].primary_key
        assert fk.req_ids == rel.req_ids  # 파생 객체는 관계의 근거를 물려받는다
        return [c.physical_name for c in child.columns if c.id in fk.columns]

    # 설비 → 고장접수, 고장접수 → 보전작업, 팀 → 보전작업 (A04 반환 순서)
    assert fk_names(0) == ["eqpm_cd"]
    assert fk_names(1) == ["bkdn_rcpt_no"]
    assert fk_names(2) == ["team_cd"]
    # 비식별 관계라 자식 PK는 자기 키 그대로
    work = tables[entities["보전작업"].id]
    assert [c.physical_name for c in work.columns if c.id in work.primary_key] == ["job_no"]
    assert state.model_dump(mode="json") == before
