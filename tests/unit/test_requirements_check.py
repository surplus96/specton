"""#17 분석 확인(HITL 1, UI-03): 확인할 것이 있을 때만 멈춘다 (ADR-0015 결정 1).

멈추는 조건: 품질 경고·질문(`quality_issues`), 분할(같은 원문 `source_ref`에서 요구사항 2건 이상).
"""

from collections.abc import Mapping
from itertools import pairwise
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.contracts import DesignState, Requirement, RunState
from specton.contracts.requirements import QualityIssue
from specton.graph import GraphState, Node, build_graph, initial_state
from specton.persistence.runs import can_transition

APPROVE = {"kind": "review", "decision": "approve", "feedback": ""}
AMBIGUOUS = QualityIssue(kind="ambiguous", message="「빠르게」의 기준이 없습니다")


def _req(n: int, row: int, type_: str = "FR", **extra: Any) -> Requirement:
    return Requirement.model_validate(
        {
            "id": f"REQ-{n:02d}",
            "source_ref": {"file_format": "csv", "row": row},
            "text": "입고를 등록한다",
            "draft_text": "입고를 등록한다",
            "type": type_,
            "nfr_category": "performance" if type_ == "NFR" else None,
            "analysis_version": 1,
            **extra,
        }
    )


class _Run:
    """A01 자리에 고정 요구사항을 넣는 그래프. 방문한 노드를 남긴다."""

    def __init__(self, *requirements: Requirement) -> None:
        self.visited: list[str] = []
        self.config = {"configurable": {"thread_id": "run-1"}}

        def a01(state: GraphState) -> Mapping[str, Any]:
            self.visited.append("a01")
            return {"design": state["design"].evolve(requirements=requirements)}

        def a02(state: GraphState) -> Mapping[str, Any]:
            self.visited.append("a02")
            return {}

        nodes: dict[str, Node] = {"a01": a01, "a02": a02}
        self.graph = build_graph(nodes, checkpointer=InMemorySaver())

    def start(self) -> dict[str, Any]:
        return self.graph.invoke(initial_state(DesignState(run_id="run-1")), self.config)


def _kind(result: Mapping[str, Any]) -> str:
    (pending,) = result["__interrupt__"]
    kind: str = pending.value["kind"]
    return kind


def test_requirements_without_anything_to_check_go_to_design_without_stopping() -> None:
    run = _Run(_req(1, 2), _req(2, 3, "NFR"))

    result = run.start()

    assert _kind(result) == "review"  # 분석 확인을 건너뛰고 최종 검토까지 간다
    assert run.visited == ["a01", "a02"]


def test_quality_issue_stops_for_the_requirements_check() -> None:
    run = _Run(_req(1, 2), _req(2, 3, quality_issues=[AMBIGUOUS]))

    result = run.start()

    assert _kind(result) == "requirements"
    assert result["design"].status is RunState.AWAITING_REQUIREMENTS
    assert run.visited == ["a01"]


def test_question_for_the_user_stops_for_the_requirements_check() -> None:
    question = QualityIssue(kind="unclear", message="보관 기간이 없습니다", question="몇 년입니까?")
    run = _Run(_req(1, 2, quality_issues=[question]))

    assert _kind(run.start()) == "requirements"


def test_split_from_one_source_stops_for_the_requirements_check() -> None:
    """같은 원문에서 요구사항이 2건 이상이면 분할이다. 새 계약 칸 없이 개수로 센다."""
    run = _Run(_req(1, 2), _req(2, 2))

    assert _kind(run.start()) == "requirements"


def test_functional_and_non_functional_split_also_stops() -> None:
    run = _Run(_req(1, 2), _req(2, 2, "NFR"))

    assert _kind(run.start()) == "requirements"


def test_skipped_check_follows_the_state_diagram() -> None:
    run = _Run(_req(1, 2))
    seen = [RunState.QUEUED]
    steps: list[Any] = [initial_state(DesignState(run_id="run-1")), Command(resume=APPROVE)]

    for step in steps:
        for chunk in run.graph.stream(step, run.config, stream_mode="values"):
            if chunk["design"].status != seen[-1]:
                seen.append(chunk["design"].status)

    assert RunState.AWAITING_REQUIREMENTS not in seen
    assert (RunState.ANALYSING, RunState.DESIGNING) in list(pairwise(seen))
    assert [(a, b) for a, b in pairwise(seen) if not can_transition(a, b)] == []
    assert seen[-1] is RunState.COMPLETED
