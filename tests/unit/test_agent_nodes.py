"""#17 에이전트 노드를 그래프 노드로 잇기. 실제 LLM 없이 stub 응답으로 확인한다.

고정 응답은 maintenance 예시이고, 각 단계의 입력은 앞 단계가 상태에 남긴 값이다.
"""

from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.agent_nodes import design_nodes, openai_design_nodes
from specton.api.main import create_graph
from specton.config import Settings
from specton.contracts import DesignState
from specton.contracts.requirements import RequirementDraft, SourceRequirement
from specton.contracts.state import VersionInfo
from specton.graph import DocumentRef, build_graph, initial_state
from specton.llm.client import LLMClient
from specton.llm.errors import LLMAPIError
from specton.llm.stub import reply, stub_client
from specton.nodes import a01_requirements, a03_entities
from specton.nodes.a01_requirements import A01Output
from specton.nodes.a02_functions import A02Output
from specton.nodes.a03_entities import A03Output
from specton.nodes.a04_relationships import A04Output
from specton.packs.examples import load_examples

PACK = "maintenance"
REQUIREMENTS_OK = {"kind": "requirements", "answers": []}


def _settings() -> Settings:
    return Settings(_env_file=None)


def _example_requirements() -> list[dict[str, Any]]:
    [example] = load_examples(PACK, "A02", A02Output)
    requirements: list[dict[str, Any]] = example.input["requirements"]
    return requirements


def _design(**versions: str) -> DesignState:
    """A02 예시의 요구사항 문장을 행 하나씩 원문 블록으로 둔 실행 상태."""
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
    return DesignState(run_id="run-1", source_requirements=blocks, versions=VersionInfo(**versions))


def _a01_output() -> A01Output:
    """블록마다 요구사항 하나. 코드가 붙이는 ID가 A02 예시의 REQ-01~04와 같아진다."""
    return A01Output(
        requirements=tuple(
            RequirementDraft.model_validate(
                {
                    "source_block_ids": [f"csv:{n + 2}"],
                    "text": r["text"],
                    "type": r["type"],
                    "nfr_category": r["nfr_category"],
                }
            )
            for n, r in enumerate(_example_requirements())
        )
    )


def _a04_output() -> A04Output:
    return A04Output.model_validate(
        {
            "relationships": [
                {
                    "parent_name": "설비",
                    "child_name": "고장접수",
                    "cardinality": "1:N",
                    "optional": False,
                    "rationale": '"한 접수는 한 설비에 대한 것이며"',
                    "req_ids": ["REQ-01"],
                }
            ]
        }
    )


def _example_output[T](agent: str, model: type[T]) -> T:
    [example] = load_examples(PACK, agent, model)  # type: ignore[type-var]
    output: T = example.output
    return output


def _nodes(client: LLMClient) -> dict[str, Any]:
    return dict(design_nodes(lambda: client, _settings()))


def test_a01_node_puts_requirements_into_the_design_and_records_versions() -> None:
    client, _ = stub_client(reply(_a01_output()))
    design = _design(pack_id=PACK, pack_version="0.1.4")

    update = _nodes(client)["a01"](initial_state(design))

    result: DesignState = update["design"]
    assert [r.id for r in result.requirements] == ["REQ-01", "REQ-02", "REQ-03", "REQ-04"]
    assert result.versions.prompt_versions == {"A01": a01_requirements.PROMPT_VERSION}
    assert result.versions.model_names == {"A01": _settings().design_model}
    assert result.versions.pack_id == PACK


def test_a03_node_updates_entities_and_the_functions_that_use_them() -> None:
    client, _ = stub_client(
        reply(_a01_output()),
        reply(_example_output("A02", A02Output)),
        reply(_example_output("A03", A03Output)),
    )
    nodes = _nodes(client)
    state = initial_state(_design(pack_id=PACK))
    for name in ("a01", "a02"):
        state = {**state, **nodes[name](state)}

    update = nodes["a03"](state)

    result: DesignState = update["design"]
    assert result.entities
    assert all(f.entity_ops for f in result.functions)
    assert result.versions.prompt_versions["A03"] == a03_entities.PROMPT_VERSION


def test_node_fails_when_the_run_has_no_pack() -> None:
    client, transport = stub_client(reply(_a01_output()))

    with pytest.raises(ValueError, match="팩"):
        _nodes(client)["a01"](initial_state(_design()))

    assert transport.sent == ()


def test_openai_nodes_build_without_an_api_key_and_fail_only_when_called() -> None:
    nodes = openai_design_nodes(Settings(_env_file=None, openai_api_key=None))

    with pytest.raises(LLMAPIError):
        nodes["a01"](initial_state(_design(pack_id=PACK)))


def test_app_graph_reads_the_document_and_runs_the_real_design_nodes(tmp_path: Path) -> None:
    """빈 노드는 문서를 읽지도 LLM을 부르지도 않는다.

    올린 CSV를 읽어 A01까지 가고, 키 없는 설정에서 A01이 실패하면 실제 노드가 연결된 것이다.
    """
    (tmp_path / "a.csv").write_text(
        "요구사항 ID,요구사항명,상세 내용\nSFR-001,입고 등록,입고를 등록한다\n", encoding="utf-8"
    )
    settings = Settings(_env_file=None, openai_api_key=None, storage_dir=tmp_path)
    graph = create_graph(settings, InMemorySaver())
    doc = DocumentRef(document_id="doc-1", file_format="csv", storage_ref="a.csv")
    start = initial_state(DesignState(run_id="run-1", versions=VersionInfo(pack_id=PACK)), (doc,))

    with pytest.raises(LLMAPIError):
        graph.invoke(start, {"configurable": {"thread_id": "run-1"}})

    design: DesignState = graph.get_state({"configurable": {"thread_id": "run-1"}}).values["design"]
    assert [b.block_id for b in design.source_requirements] == ["csv:2"]


def test_design_nodes_run_through_the_graph_to_the_final_review() -> None:
    client, transport = stub_client(
        reply(_a01_output()),
        reply(_example_output("A02", A02Output)),
        reply(_example_output("A03", A03Output)),
        reply(_a04_output()),
    )
    graph = build_graph(_nodes(client), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "run-1"}}

    first = graph.invoke(initial_state(_design(pack_id=PACK)), config)
    review = graph.invoke(Command(resume=REQUIREMENTS_OK), config)

    assert first["__interrupt__"][0].value["kind"] == "requirements"
    assert review["__interrupt__"][0].value["kind"] == "review"
    design: DesignState = review["design"]
    assert design.requirements and design.functions and design.entities
    assert [r.parent for r in design.relationships] == [
        e.id for e in design.entities if e.name == "설비"
    ]
    assert set(design.versions.prompt_versions) == {"A01", "A02", "A03", "A04"}
    assert [r.stage for r in transport.sent] == ["A01", "A02", "A03", "A04"]
