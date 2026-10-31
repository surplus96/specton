"""A02 → A03 → A04 → A08 연속 호출. 앞 run()의 실제 반환값을 상태에 넣어 다음 단계에 넘긴다.

노드 사이의 데이터 연결만 고정 응답(stub)으로 확인한다. 실제 LLM의 품질이나 그래프(#17) 전체
실행을 검증하지 않는다. 고정 응답은 maintenance 예시와 이 파일의 값이지만, 각 단계의 입력 상태는
앞 단계 반환값으로만 만든다.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from specton.config import Settings
from specton.contracts import DesignState, FindingDraft, Function, Relationship, Requirement
from specton.contracts.state import find_trace_issues
from specton.llm.stub import reply, stub_client
from specton.nodes import a02_functions, a03_entities, a04_relationships
from specton.nodes.a02_functions import A02Output
from specton.nodes.a03_entities import A03Output, A03Result
from specton.nodes.a04_relationships import A04Output
from specton.nodes.common import unwrap_data
from specton.packs.examples import load_examples
from specton.review.merge import merge_review
from specton.review.perspective import PERSPECTIVES_DIR, load_perspective
from specton.review.reviewer import ReviewOutput, ReviewRun, review_perspective

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
            source_ref={"kind": "csv", "row": n + 2},
            text=r["text"],
            original_text=r["text"],
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


def _finding(target_id: str, quote: str = REPORTER_QUOTE) -> FindingDraft:
    """근거 연결만 본다. 지적 내용이 맞는 판단인지는 stub으로 알 수 없다."""
    return FindingDraft(
        kind="duplicated_fact",
        severity="major",
        targets=[{"kind": "attribute", "id": target_id}],
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
    state = _run_design().state

    _, sent = _review(state)

    # A08 inputs는 requirements·entities다. 앞에서 A04를 돌려도 relationships는 보내지 않는다
    assert set(A08.inputs) == {"requirements", "entities"}
    data = _data(sent[0])
    assert set(data) == {"requirements", "entities"}
    assert data["requirements"] == [r.model_dump(mode="json") for r in state.requirements]
    assert data["entities"] == [e.model_dump(mode="json") for e in state.entities]


def test_grounded_a08_finding_survives_the_common_merge() -> None:
    state = _run_design().state
    target_id = _attribute_id(state, "고장접수", "신고자식별값")

    run, _ = _review(state, _finding(target_id))
    merged = merge_review(state, run.results, ("A08",))

    assert (merged.complete, merged.rejected) == (True, ())
    (finding,) = merged.findings
    assert (finding.reviewer_id, finding.targets[0].id) == ("A08", target_id)
    assert finding.evidence[0].quote == REPORTER_QUOTE


def test_a08_finding_without_real_target_or_quote_is_rejected_by_the_common_merge() -> None:
    state = _run_design().state
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
    state = _run_design().state

    run, _ = _review(state)
    merged = merge_review(state, run.results, ("A08",))

    assert run.complete
    assert (merged.complete, merged.findings, merged.rejected) == (True, (), ())


def test_review_does_not_change_the_design_state() -> None:
    state = _run_design().state
    before = state.model_dump(mode="json")
    target_id = _attribute_id(state, "고장접수", "신고자식별값")

    run, _ = _review(state, _finding(target_id))
    merge_review(state, run.results, ("A08",))

    assert state.model_dump(mode="json") == before
