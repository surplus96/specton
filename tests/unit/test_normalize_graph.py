"""모델 정리 자리(`normalize`)에 실제로 도착하는 상태 (#12, main #121·#122 기준).

실제 설계 노드(A01~A04, `agent_nodes.design_nodes`)를 고정 응답(stub)으로 그래프에 태우고,
`normalize` 자리에 엿보기 노드를 끼운다. 엿보기 노드는 도착한 상태를 기록하고 정리 함수를 부르지만
**상태에는 아무것도 넣지 않는다.** 정리 결과를 담을 그래프·설계 상태 칸이 아직 없어서다.
그래서 이 테스트는 "정리 함수가 그래프 입력을 그대로 받는다"까지를 확인한다.
연결 완료를 뜻하지 않는다.

- 팩: 실행기처럼 첫 상태 `versions`에 팩 ID·버전을 넣는다(#121 `runs.load_versions`).
  버전은 API가 run을 만들 때처럼 팩 manifest에서 읽는다.
- 앞 단계 결과(엔티티·관계)는 바꾸지 않고, 실제 팩의 공식 이음동의어로 정리한다.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.agent_nodes import design_nodes
from specton.codegen.model import Normalized, NormalizeFailed, NormalizeResult
from specton.codegen.naming import (
    DEFAULT_PACK_ROOT,
    load_naming_rules,
    load_pack_lexicon,
)
from specton.codegen.normalize import PackRef, normalize
from specton.codegen.normalize_step import normalize_from_state
from specton.config import Settings
from specton.contracts import DesignState
from specton.contracts.requirements import QualityIssue, RequirementDraft, SourceRequirement
from specton.contracts.state import VersionInfo
from specton.graph import GraphState, build_graph, initial_state
from specton.llm.stub import reply, stub_client
from specton.nodes.a01_requirements import A01Output
from specton.nodes.a02_functions import A02Output
from specton.nodes.a03_entities import A03Output
from specton.nodes.a04_relationships import A04Output
from specton.nodes.common import unwrap_data
from specton.packs.build import read_yaml
from specton.packs.examples import load_examples

PACK = "maintenance"
PACK_VERSION = str(read_yaml(DEFAULT_PACK_ROOT / PACK / "manifest.yaml")["version"])
DESIGN_FIELDS = ("requirements", "functions", "entities", "relationships", "versions")


def _example_requirements() -> list[dict[str, Any]]:
    [example] = load_examples(PACK, "A02", A02Output)
    requirements: list[dict[str, Any]] = example.input["requirements"]
    return requirements


def _start() -> GraphState:
    """A02 예시 요구사항을 원문 블록으로 둔 첫 상태. 팩은 실행기가 넣는 값과 같다."""
    blocks = tuple(
        SourceRequirement(
            document_id="doc-1",
            block_id=f"csv:{n + 2}",
            source_ref={"file_format": "csv", "row": n + 2},
            source_text=r["text"],
            extraction_status="pass",
        )
        for n, r in enumerate(_example_requirements())
    )
    versions = VersionInfo(pack_id=PACK, pack_version=PACK_VERSION)
    return initial_state(DesignState(run_id="run-1", source_requirements=blocks, versions=versions))


def _a01_output(*, with_issue: bool) -> A01Output:
    """블록마다 요구사항 하나. `with_issue`면 첫 요구사항에 품질 경고를 달아 HITL 1에서 멈춘다."""
    issue = [QualityIssue(kind="ambiguous", message="기준이 없는 표현이 있습니다")]
    return A01Output(
        requirements=tuple(
            RequirementDraft.model_validate(
                {
                    "source_block_ids": [f"csv:{n + 2}"],
                    "text": r["text"],
                    "type": r["type"],
                    "nfr_category": r["nfr_category"],
                    "quality_issues": issue if with_issue and n == 0 else [],
                }
            )
            for n, r in enumerate(_example_requirements())
        )
    )


def _example_output[T](agent: str, model: type[T]) -> T:
    [example] = load_examples(PACK, agent, model)  # type: ignore[type-var]
    output: T = example.output
    return output


def _a04_output() -> A04Output:
    """A02 예시의 요구사항 문장을 인용한 관계 (test_design_chain과 같은 사례)."""

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


class _Probe:
    """`normalize` 자리 엿보기 노드.

    도착한 설계 상태와 정리 결과를 기록하고, 상태는 바꾸지 않는다.
    """

    def __init__(self, run: Callable[[Mapping[str, Any]], NormalizeResult]) -> None:
        self.run = run
        self.arrived: list[DesignState] = []
        self.results: list[NormalizeResult] = []

    def __call__(self, state: GraphState) -> Mapping[str, Any]:
        self.arrived.append(state["design"])
        self.results.append(self.run(state))
        return {}


def _run_graph(
    probe: _Probe, *, with_issue: bool, answers: tuple[dict[str, Any], ...] = ()
) -> tuple[dict[str, Any], list[Any], list[str]]:
    """설계 노드를 그래프로 돌려 HITL 2에서 멈춘 결과, LLM 요청, 멈춘 지점을 돌려준다.

    HITL 1에서 멈추면 `answers`(요구사항별 keep·edit·split, #123)로 답한다.
    """
    client, transport = stub_client(
        reply(_a01_output(with_issue=with_issue)),
        reply(_example_output("A02", A02Output)),
        reply(_example_output("A03", A03Output)),
        reply(_a04_output()),
    )
    nodes = {**design_nodes(lambda: client, Settings(_env_file=None)), "normalize": probe}
    graph = build_graph(nodes, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "run-1"}}
    stops: list[str] = []
    result = graph.invoke(_start(), config)
    while result["__interrupt__"][0].value["kind"] != "review":
        stops.append(result["__interrupt__"][0].value["kind"])
        answer = {"kind": "requirements", "answers": list(answers)}
        result = graph.invoke(Command(resume=answer), config)
    stops.append("review")
    return result, transport.sent, stops


def _same_design(a: DesignState, b: DesignState) -> bool:
    return all(getattr(a, f) == getattr(b, f) for f in DESIGN_FIELDS)


def test_skip_path_brings_the_a04_design_and_the_run_pack_to_normalize() -> None:
    """#122: 확인할 것이 없으면 HITL 1을 건너뛰고 A02~A04를 거쳐 normalize에 온다."""
    probe = _Probe(normalize_from_state)

    final, sent, stops = _run_graph(probe, with_issue=False)

    assert [r.stage for r in sent] == ["A01", "A02", "A03", "A04"]
    assert stops == ["review"]  # 요구사항 확인에서 멈추지 않았다
    (arrived,) = probe.arrived
    assert (arrived.versions.pack_id, arrived.versions.pack_version) == (PACK, PACK_VERSION)
    assert arrived.entities and len(arrived.relationships) == 3
    # 공식 이음동의어 정책으로 실제 팩에서 정리된다.
    (result,) = probe.results
    assert isinstance(result, Normalized)
    # 정리는 설계 상태를 바꾸지 않고, 정리 결과는 그래프 상태 어디에도 남지 않는다 (미연결)
    assert _same_design(final["design"], arrived)
    assert not any(isinstance(v, (Normalized, NormalizeFailed)) for v in final.values())


def _requirement_texts(design: DesignState) -> dict[str, str]:
    return {r.id: r.text for r in design.requirements}


def _a02_requirement_ids(sent: list[Any]) -> list[str]:
    """A02 요청에 실제로 실려 간 요구사항 ID."""
    data = json.loads(unwrap_data(sent[1].messages[-1].content))
    return [r["id"] for r in data["requirements"]]


@pytest.mark.parametrize("action", ["keep", "edit", "split"])
def test_requirements_check_answers_reach_normalize(action: str) -> None:
    """품질 경고가 있으면 HITL 1에서 멈추고, 답(#123)을 반영한 요구사항으로 A02~A04를 거쳐 온다.

    수정·분할 문장은 원래 문장을 그대로 포함하게 둔다. A02·A04 고정 응답의 근거 인용이
    원래 문장을 가리키기 때문이다 (앞 단계 결과를 바꾸지 않기 위해).
    """
    skipped = _Probe(normalize_from_state)
    _run_graph(skipped, with_issue=False)
    original = _requirement_texts(skipped.arrived[0])
    edited = original["REQ-03"] + " 확인함."
    added = "변경 이력은 1년간 보관한다."
    answers: dict[str, tuple[dict[str, Any], ...]] = {
        "keep": (),
        "edit": ({"req_id": "REQ-03", "action": "edit", "texts": [edited]},),
        "split": ({"req_id": "REQ-04", "action": "split", "texts": [original["REQ-04"], added]},),
    }

    checked = _Probe(normalize_from_state)
    _, sent, stops = _run_graph(checked, with_issue=True, answers=answers[action])

    assert [r.stage for r in sent] == ["A01", "A02", "A03", "A04"]
    assert stops == ["requirements", "review"]
    (arrived,) = checked.arrived
    expected = dict(original)
    if action == "edit":
        expected["REQ-03"] = edited
    if action == "split":
        expected["REQ-05"] = added
        (piece,) = [r for r in arrived.requirements if r.id == "REQ-05"]
        (parent,) = [r for r in arrived.requirements if r.id == "REQ-04"]
        assert piece.source_ref == parent.source_ref  # 분할 조각은 부모 원문을 가리킨다
    assert _requirement_texts(arrived) == expected
    # 답을 반영한 요구사항이 A02에 실려 가고, 같은 엔티티·관계가 normalize에 도착한다
    assert _a02_requirement_ids(sent) == list(expected)
    assert arrived.entities == skipped.arrived[0].entities
    assert arrived.relationships == skipped.arrived[0].relationships
    # 사용자 답 반영 후에도 추적·키·관계와 공식 이음동의어 명명이 유효하다.
    (result,) = checked.results
    assert isinstance(result, Normalized)


def test_graph_input_normalizes_with_the_real_official_alias_dictionary() -> None:
    """그래프가 보낸 설계를 실제 팩으로 정리해 FK와 원래 근거를 보존한다."""
    lexicon = load_pack_lexicon(PACK)

    def with_real_pack(state: Mapping[str, Any]) -> NormalizeResult:
        design: DesignState = state["design"]
        version = design.versions.pack_version
        assert version is not None
        return normalize(
            design, pack=PackRef(PACK, version), lexicon=lexicon, rules=load_naming_rules()
        )

    probe = _Probe(with_real_pack)
    _run_graph(probe, with_issue=False)

    (arrived,) = probe.arrived
    (result,) = probe.results
    assert isinstance(result, Normalized), result
    tables = {t.entity_id: t for t in result.model.tables}
    fk_names = []
    for rel in arrived.relationships:
        (fk,) = [f for f in result.model.foreign_keys if f.relationship_id == rel.id]
        assert fk.req_ids == rel.req_ids
        child = tables[rel.child]
        fk_names.append([c.physical_name for c in child.columns if c.id in fk.columns])
    assert fk_names == [["eqpm_cd"], ["bkdn_rcpt_no"], ["team_cd"]]
