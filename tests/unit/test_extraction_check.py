"""#17 추출 확인(UI-02): `review`·`fail` 블록이 있을 때만 멈추고, 답을 블록 결정으로 남긴다.

ADR-0015 결정 1·5, docs/06 resume. 422 검사는 resume API(#120)가 먼저 한다.
"""

from collections.abc import Mapping
from itertools import pairwise
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.contracts import DesignState, RunState
from specton.contracts.requirements import SourceRequirement
from specton.graph import ExtractionFailedError, GraphState, Node, build_graph, initial_state
from specton.persistence.runs import can_transition

REQUIREMENTS_OK = {"kind": "requirements", "answers": []}


def _block(n: int, status: str, text: str | None = "입고를 등록한다") -> SourceRequirement:
    return SourceRequirement(
        document_id="doc-1",
        block_id=f"csv:{n}",
        source_ref={"file_format": "csv", "row": n},
        source_text=text,
        extraction_status=status,
    )


def _extraction(*excluded: tuple[str, str | None]) -> dict[str, Any]:
    blocks = [{"block_id": b, "reason": r} for b, r in excluded]
    return {"kind": "extraction", "confirmed": True, "excluded_blocks": blocks}


class _Run:
    """parse 자리에 고정 블록을 넣고 A01이 받은 상태를 남기는 그래프."""

    def __init__(self, *blocks: SourceRequirement) -> None:
        self.analysed: list[DesignState] = []
        self.config = {"configurable": {"thread_id": "run-1"}}

        def parse(state: GraphState) -> Mapping[str, Any]:
            return {"design": state["design"].evolve(source_requirements=blocks)}

        def a01(state: GraphState) -> Mapping[str, Any]:
            self.analysed.append(state["design"])
            return {}

        nodes: dict[str, Node] = {"parse": parse, "a01": a01}
        self.graph = build_graph(nodes, checkpointer=InMemorySaver())

    def start(self) -> dict[str, Any]:
        return self.graph.invoke(initial_state(DesignState(run_id="run-1")), self.config)

    def resume(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return self.graph.invoke(Command(resume=dict(value)), self.config)


def _kind(result: Mapping[str, Any]) -> str:
    (pending,) = result["__interrupt__"]
    kind: str = pending.value["kind"]
    return kind


def _decisions(design: DesignState) -> dict[str, tuple[str | None, str | None]]:
    return {b.block_id: (b.user_decision, b.excluded_reason) for b in design.source_requirements}


def test_all_pass_blocks_go_to_analysis_without_stopping() -> None:
    run = _Run(_block(2, "pass"), _block(3, "pass"))

    result = run.start()

    assert _kind(result) == "requirements"
    assert len(run.analysed) == 1


def test_review_block_stops_for_the_extraction_check_before_analysis() -> None:
    run = _Run(_block(2, "pass"), _block(3, "review"))

    result = run.start()

    assert _kind(result) == "extraction"
    assert result["design"].status is RunState.AWAITING_INPUT
    assert run.analysed == []


def test_fail_block_also_stops_for_the_extraction_check() -> None:
    run = _Run(_block(2, "pass"), _block(3, "fail"))

    assert _kind(run.start()) == "extraction"


def test_answer_is_kept_as_block_decisions_and_moves_to_analysis() -> None:
    run = _Run(_block(2, "pass"), _block(3, "review"), _block(4, "review"), _block(5, "fail"))
    run.start()

    result = run.resume(_extraction(("csv:4", "2차 범위"), ("csv:5", None)))

    assert _kind(result) == "requirements"
    [design] = run.analysed
    assert _decisions(design) == {
        "csv:2": (None, None),
        "csv:3": ("confirmed", None),
        "csv:4": ("excluded", "2차 범위"),
        "csv:5": ("excluded", None),
    }
    assert [b.block_id for b in design.source_requirements if b.analysable] == ["csv:2", "csv:3"]


def test_blank_reason_for_a_fail_block_is_kept_as_no_reason() -> None:
    """화면이 빈 입력칸을 `""`로 보내도 계약의 `excluded_reason`(빈 문자열 금지)에 맞춘다 (#120)."""
    run = _Run(_block(2, "pass"), _block(3, "fail"))
    run.start()

    run.resume(_extraction(("csv:3", "   ")))

    [design] = run.analysed
    assert _decisions(design)["csv:3"] == ("excluded", None)


def test_run_fails_when_no_block_is_left_to_analyse() -> None:
    run = _Run(_block(2, "review"), _block(3, "review", text=None))
    run.start()

    with pytest.raises(ExtractionFailedError):
        run.resume(_extraction(("csv:2", "범위 밖")))

    assert run.analysed == []


def test_answered_check_moves_to_the_same_status_as_the_resume_api() -> None:
    """resume API는 추출 확인 답을 받으면 `analysing`으로 바꾼다 (#110). 노드도 같아야 한다."""
    run = _Run(_block(2, "review"))
    run.start()

    updates = list(
        run.graph.stream(Command(resume=_extraction()), run.config, stream_mode="updates")
    )

    (answered,) = [u["hitl_extraction"] for u in updates if "hitl_extraction" in u]
    assert answered["design"].status is RunState.ANALYSING


def test_status_changes_with_the_extraction_check_follow_the_state_diagram() -> None:
    run = _Run(_block(2, "review"))
    seen = [RunState.QUEUED]
    steps: list[Any] = [initial_state(DesignState(run_id="run-1"))]
    steps += [Command(resume=_extraction()), Command(resume=REQUIREMENTS_OK)]

    for step in steps:
        for chunk in run.graph.stream(step, run.config, stream_mode="values"):
            if chunk["design"].status != seen[-1]:
                seen.append(chunk["design"].status)

    assert seen[:4] == [
        RunState.QUEUED,
        RunState.PARSING,
        RunState.AWAITING_INPUT,
        RunState.ANALYSING,
    ]
    assert [(a, b) for a, b in pairwise(seen) if not can_transition(a, b)] == []
