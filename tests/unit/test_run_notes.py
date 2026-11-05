"""#17 실행 기록: 관련 요구사항 경고(ADR-0015 결정 5)와 LLM 호출 기록 로그 (docs/13 비용 확인).

- 제외한 원문의 `source_id`가 남은 원문의 「관련 요구사항」에 나오면 추출 확인 노드가 경고를 남긴다.
  실행기가 `run_event`(status 이벤트)로 기록한다. 제외는 막지 않는다.
- 노드는 호출 기록(`CallRecord`)을 한 줄씩 로그로 남긴다. 원문·키는 남기지 않는다.
"""

import logging
from collections.abc import Mapping
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.agent_nodes import design_nodes
from specton.config import Settings
from specton.contracts import DesignState
from specton.contracts.requirements import SourceRequirement
from specton.contracts.state import VersionInfo
from specton.graph import GraphState, Node, build_graph, initial_state
from specton.llm.errors import LLMRefusalError
from specton.llm.stub import refusal, reply, stub_client
from specton.nodes.a01_requirements import A01Output


def _block(
    n: int, source_id: str | None, related: str | None = None, status: str = "review"
) -> Any:
    return SourceRequirement(
        document_id="doc-1",
        block_id=f"csv:{n}",
        source_id=source_id,
        source_ref={"file_format": "csv", "row": n},
        source_text=f"요구사항 {n}",
        source_related_requirements=related,
        extraction_status=status,
        notice=None if status == "pass" else "확인이 필요한 블록",
    )


def _answer_notes(*blocks: SourceRequirement, excluded: tuple[str, ...]) -> list[dict[str, Any]]:
    """추출 확인에서 `excluded`를 제외했을 때 추출 확인 노드가 남긴 기록."""

    def parse(state: GraphState) -> Mapping[str, Any]:
        return {"design": state["design"].evolve(source_requirements=blocks)}

    nodes: dict[str, Node] = {"parse": parse}
    graph = build_graph(nodes, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "run-1"}}
    graph.invoke(initial_state(DesignState(run_id="run-1")), config)
    answer = {
        "kind": "extraction",
        "confirmed": True,
        "excluded_blocks": [{"block_id": b, "reason": "범위 밖"} for b in excluded],
    }
    updates = list(graph.stream(Command(resume=answer), config, stream_mode="updates"))
    [answered] = [u["hitl_extraction"] for u in updates if "hitl_extraction" in u]
    notes: list[dict[str, Any]] = list(answered.get("notes", ()))
    return notes


def test_excluding_a_requirement_named_as_related_by_another_leaves_a_warning() -> None:
    notes = _answer_notes(
        _block(2, "SFR-001", related="SFR-003, SFR-009"),
        _block(3, "SFR-003"),
        _block(4, "SFR-004", related="SFR-003"),
        excluded=("csv:3",),
    )

    assert notes == [
        {
            "message": "제외한 원문을 관련 요구사항으로 적은 원문이 있습니다",
            "payload": {
                "warning": "excluded_related",
                "block_id": "csv:3",
                "source_id": "SFR-003",
                "related_block_ids": ["csv:2", "csv:4"],
            },
        }
    ]


def test_ids_are_matched_as_whole_ids() -> None:
    """「SFR-0031」 안의 「SFR-003」은 같은 ID가 아니다."""
    notes = _answer_notes(
        _block(2, "SFR-001", related="SFR-0031"),
        _block(3, "SFR-003"),
        excluded=("csv:3",),
    )

    assert notes == []


def test_related_text_of_another_excluded_block_does_not_warn() -> None:
    notes = _answer_notes(
        _block(2, "SFR-001", related="SFR-003"),
        _block(3, "SFR-003"),
        _block(4, "SFR-004"),
        excluded=("csv:2", "csv:3"),
    )

    assert notes == []  # 관련 요구사항으로 적은 원문도 함께 뺐다


# LLM 호출 기록 로그

PACK = "inventory"
A01_REPLY = A01Output.model_validate(
    {"requirements": [{"source_block_ids": ["csv:2"], "text": "요구사항 2", "type": "FR"}]}
)


def _a01_state() -> GraphState:
    design = DesignState(
        run_id="run-1",
        source_requirements=(_block(2, "SFR-001", status="pass"),),
        versions=VersionInfo(pack_id=PACK),
    )
    return initial_state(design)


def _call_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("LLM 호출")]


def test_node_logs_each_model_call(caplog: pytest.LogCaptureFixture) -> None:
    client, _ = stub_client(reply(A01_REPLY, input_tokens=120, output_tokens=30))
    node = design_nodes(lambda: client, Settings(_env_file=None))["a01"]

    with caplog.at_level(logging.INFO, logger="specton.agent_nodes"):
        node(_a01_state())

    [line] = _call_lines(caplog)
    assert "run=run-1 stage=A01" in line
    assert "input_tokens=120 output_tokens=30" in line
    assert "요구사항 2" not in line  # 원문은 남기지 않는다


def test_failed_calls_are_logged_before_the_failure_goes_up(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = stub_client(refusal())
    node = design_nodes(lambda: client, Settings(_env_file=None))["a01"]

    with (
        caplog.at_level(logging.INFO, logger="specton.agent_nodes"),
        pytest.raises(LLMRefusalError),
    ):
        node(_a01_state())

    [line] = _call_lines(caplog)
    assert "stage=A01" in line and "outcome=refused" in line
