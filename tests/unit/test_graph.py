"""#17 설계 그래프: 빈 노드(stub)로 단계 연결·HITL 멈춤과 재개·병렬 합류·재작업 상한 (03 문서)."""

from collections.abc import Callable, Mapping
from itertools import pairwise
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.contracts import BranchResult, DesignState, Finding, Requirement, RunState
from specton.contracts.base import TargetStage
from specton.graph import (
    GENERATORS,
    REVIEWERS,
    GraphState,
    Node,
    build_graph,
    initial_state,
)
from specton.persistence.runs import can_transition
from specton.review.rework import HitlReason

REQ = Requirement(
    id="REQ-01",
    source_ref={"file_format": "csv", "row": 2},
    text="입고를 등록한다",
    draft_text="입고를 등록한다",
    type="FR",
    analysis_version=1,
)
REQUIREMENTS_OK = {"kind": "requirements", "answers": []}
APPROVE = {"kind": "review", "decision": "approve", "feedback": ""}


def _design() -> DesignState:
    return DesignState(run_id="run-1", requirements=[REQ])


def _finding(fingerprint: str, stage: TargetStage | None, iteration: int) -> Finding:
    return Finding.model_validate(
        {
            "id": f"A05-{iteration}-{fingerprint}",
            "source": "llm",
            "reviewer_id": "A05",
            "kind": "missing_function",
            "severity": "major",
            "targets": [{"kind": "requirement", "id": "REQ-01"}],
            "evidence": [{"req_id": "REQ-01", "quote": "입고"}],
            "suggestion": "기능을 추가한다",
            "target_stage": stage,
            "fingerprint": fingerprint,
            "iteration": iteration,
        }
    )


def _reviewer(findings_for: Callable[[DesignState], tuple[Finding, ...]]) -> Node:
    """A05 자리에 넣는 리뷰어. 현재 상태를 보고 지적을 낸다."""

    def node(state: GraphState) -> Mapping[str, Any]:
        design = state["design"]
        result = BranchResult(
            branch="A05", revision=design.revision, ok=True, findings=findings_for(design)
        )
        return {"branches": {"A05": result}}

    return node


class _Run:
    """그래프 한 번 실행. 방문한 노드를 순서대로 남긴다."""

    def __init__(
        self,
        nodes: Mapping[str, Node] | None = None,
        *,
        max_rework: int = 3,
        saver: InMemorySaver | None = None,
    ) -> None:
        self.visited: list[str] = []
        self.saver = saver or InMemorySaver()
        self.config = {"configurable": {"thread_id": "run-1"}}
        self.graph = build_graph(
            self._recorded(nodes or {}), checkpointer=self.saver, max_rework=max_rework
        )

    def _recorded(self, nodes: Mapping[str, Node]) -> dict[str, Node]:
        names = ["a01", "a02", "a03", "a04", "rules", "export", *GENERATORS]
        wrapped = {name: self._record(name, lambda state: {}) for name in names}
        for name, node in nodes.items():
            wrapped[name] = self._record(name, node)
        return wrapped

    def _record(self, name: str, node: Node) -> Node:
        def wrapped(state: GraphState) -> Mapping[str, Any]:
            self.visited.append(name)
            return node(state)

        return wrapped

    def start(self) -> dict[str, Any]:
        return self.graph.invoke(initial_state(_design()), self.config)

    def resume(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return self.graph.invoke(Command(resume=dict(value)), self.config)

    def statuses(self, *resumes: Mapping[str, Any]) -> list[RunState]:
        """처음부터 실행하며 노드가 끝날 때마다의 run 상태를 모은다 (실행기가 저장하는 순서)."""
        seen = [RunState.QUEUED]
        steps: list[Any] = [initial_state(_design())]
        steps += [Command(resume=dict(r)) for r in resumes]
        for step in steps:
            for chunk in self.graph.stream(step, self.config, stream_mode="values"):
                if "design" in chunk and chunk["design"].status != seen[-1]:
                    seen.append(chunk["design"].status)
        return seen


def _interrupt(result: Mapping[str, Any]) -> dict[str, Any]:
    (pending,) = result["__interrupt__"]
    value: dict[str, Any] = pending.value
    return value


# 단계 연결·HITL


def test_stops_for_requirements_check_after_analysis() -> None:
    run = _Run()

    result = run.start()

    assert _interrupt(result)["kind"] == "requirements"
    assert result["design"].status == "awaiting_requirements"
    assert run.visited == ["a01"]


def test_runs_every_stage_and_completes_after_approval() -> None:
    run = _Run()
    run.start()
    review = run.resume(REQUIREMENTS_OK)

    assert _interrupt(review)["kind"] == "review"
    assert review["design"].status == "awaiting_review"

    done = run.resume(APPROVE)

    assert "__interrupt__" not in done
    assert done["design"].status == "completed"
    assert run.visited[:4] == ["a01", "a02", "a03", "a04"]
    assert run.visited[-2:] == ["rules", "export"]


def test_generation_branches_join_before_rule_check() -> None:
    run = _Run()
    run.start()
    run.resume(REQUIREMENTS_OK)

    rules = run.visited.index("rules")
    assert set(run.visited[rules - len(GENERATORS) : rules]) == set(GENERATORS)


def test_all_reviewers_join_before_merge() -> None:
    run = _Run()
    run.start()
    result = run.resume(REQUIREMENTS_OK)

    assert set(result["branches"]) >= set(REVIEWERS)
    assert all(b.ok for b in result["branches"].values())


def test_resumes_from_checkpoint_with_a_new_graph_instance() -> None:
    """서버 재시작: 같은 checkpointer와 thread_id로 새 그래프를 만들어도 멈춘 곳에서 이어간다."""
    first = _Run()
    first.start()

    restarted = _Run(saver=first.saver)
    result = restarted.resume(REQUIREMENTS_OK)

    assert _interrupt(result)["kind"] == "review"
    assert "a01" not in restarted.visited


def test_hold_at_final_review_keeps_waiting_without_export() -> None:
    """보류는 같은 확인 요청으로 계속 기다린다 (06 문서 resume, #110)."""
    run = _Run()
    run.start()
    run.resume(REQUIREMENTS_OK)

    held = run.resume({"kind": "review", "decision": "hold", "feedback": "보류"})

    assert _interrupt(held)["kind"] == "review"
    assert held["design"].status == "awaiting_review"
    assert "export" not in run.visited


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        (REQUIREMENTS_OK, RunState.DESIGNING),
        (APPROVE, RunState.EXPORTING),
        ({"kind": "review", "decision": "revise", "feedback": ""}, RunState.DESIGNING),
    ],
)
def test_answer_moves_to_the_same_status_as_the_resume_api(
    answer: Mapping[str, Any], status: RunState
) -> None:
    """답을 받은 확인 노드는 resume API(#110)가 바꾼 상태와 같은 상태를 남긴다.

    그래야 실행기가 그 노드 뒤에 저장해도 대기 상태로 되돌아가지 않는다.
    """
    run = _Run({"a09": lambda state: {"router_stage": TargetStage.FUNCTIONS}})
    run.start()
    if answer["kind"] == "review":
        run.resume(REQUIREMENTS_OK)
    hitl = "hitl_requirements" if answer["kind"] == "requirements" else "hitl_review"

    updates = list(
        run.graph.stream(Command(resume=dict(answer)), run.config, stream_mode="updates")
    )

    (answered,) = [u[hitl] for u in updates if hitl in u]
    assert answered["design"].status is status


@pytest.mark.parametrize(
    "decision",
    ["approve", "hold", "revise"],
)
def test_status_changes_follow_the_state_diagram(decision: str) -> None:
    """실행기가 노드마다 `record_progress`로 저장해도 상태 전이 검사(#108)에 걸리지 않는다."""
    run = _Run({"a09": lambda state: {"router_stage": TargetStage.FUNCTIONS}})
    final = {"kind": "review", "decision": decision, "feedback": ""}

    seen = run.statuses(REQUIREMENTS_OK, final, APPROVE)

    invalid = [(a, b) for a, b in pairwise(seen) if not can_transition(a, b)]
    assert invalid == []
    assert seen[-1] in (RunState.COMPLETED, RunState.AWAITING_REVIEW)


def test_automatic_rework_follows_the_state_diagram() -> None:
    reviewer = _reviewer(
        lambda d: (
            (_finding("fp-1", TargetStage.DATA_MODEL, d.iteration),) if d.revision == 0 else ()
        )
    )
    run = _Run({"A05": reviewer})

    seen = run.statuses(REQUIREMENTS_OK, APPROVE)

    invalid = [(a, b) for a, b in pairwise(seen) if not can_transition(a, b)]
    assert invalid == []
    assert seen[-1] is RunState.COMPLETED


def test_requirements_rework_follows_the_state_diagram() -> None:
    """요구사항 단계 재작업은 A01과 HITL 1을 다시 거친다 (`reviewing → analysing`)."""
    reviewer = _reviewer(
        lambda d: (
            (_finding("fp-1", TargetStage.REQUIREMENTS, d.iteration),) if d.revision == 0 else ()
        )
    )
    run = _Run({"A05": reviewer})

    seen = run.statuses(REQUIREMENTS_OK, REQUIREMENTS_OK, APPROVE)

    invalid = [(a, b) for a, b in pairwise(seen) if not can_transition(a, b)]
    assert invalid == []
    assert (RunState.REVIEWING, RunState.ANALYSING) in pairwise(seen)
    assert seen[-1] is RunState.COMPLETED


def test_revise_to_requirements_follows_the_state_diagram() -> None:
    """HITL 2 수정 요청을 A09가 요구사항 단계로 보내면 `designing → analysing`이다."""
    run = _Run({"a09": lambda state: {"router_stage": TargetStage.REQUIREMENTS}})
    revise = {"kind": "review", "decision": "revise", "feedback": "요구사항 보완"}

    seen = run.statuses(REQUIREMENTS_OK, revise, REQUIREMENTS_OK, APPROVE)

    invalid = [(a, b) for a, b in pairwise(seen) if not can_transition(a, b)]
    assert invalid == []
    assert (RunState.DESIGNING, RunState.ANALYSING) in pairwise(seen)
    assert seen[-1] is RunState.COMPLETED


# 재작업


def test_rework_returns_to_the_finding_stage_with_a_new_revision() -> None:
    reviewer = _reviewer(
        lambda d: (_finding("fp-1", TargetStage.FUNCTIONS, d.iteration),) if d.revision == 0 else ()
    )
    run = _Run({"A05": reviewer})
    run.start()

    result = run.resume(REQUIREMENTS_OK)

    assert run.visited.count("a02") == 2
    assert run.visited.count("a01") == 1
    assert result["design"].revision == 1
    assert _interrupt(result)["kind"] == "review"


def test_rework_stops_at_the_limit_and_asks_a_person() -> None:
    reviewer = _reviewer(
        lambda d: (_finding(f"fp-{d.revision}", TargetStage.DATA_MODEL, d.iteration),)
    )
    run = _Run({"A05": reviewer}, max_rework=3)
    run.start()

    result = run.resume(REQUIREMENTS_OK)

    assert run.visited.count("a03") == 4  # 최초 1회 + 재작업 3회
    assert _interrupt(result)["hitl_reason"] == HitlReason.LIMIT


def test_repeated_finding_asks_a_person_without_another_rework() -> None:
    reviewer = _reviewer(lambda d: (_finding("fp-same", TargetStage.DATA_MODEL, d.iteration),))
    run = _Run({"A05": reviewer})
    run.start()

    result = run.resume(REQUIREMENTS_OK)

    assert run.visited.count("a03") == 2
    assert _interrupt(result)["hitl_reason"] == HitlReason.REPEATED


def test_unrouted_finding_asks_the_router() -> None:
    reviewer = _reviewer(
        lambda d: (_finding("fp-1", None, d.iteration),) if d.revision == 0 else ()
    )
    router_calls: list[int] = []

    def router(state: GraphState) -> Mapping[str, Any]:
        router_calls.append(state["design"].revision)
        return {"router_stage": TargetStage.DATA_MODEL}

    run = _Run({"A05": reviewer, "a09": router})
    run.start()
    run.resume(REQUIREMENTS_OK)

    assert router_calls == [0]
    assert run.visited.count("a03") == 2
    assert run.visited.count("a02") == 1


def test_undecided_router_asks_a_person() -> None:
    reviewer = _reviewer(lambda d: (_finding("fp-1", None, d.iteration),))
    run = _Run({"A05": reviewer, "a09": lambda state: {"router_stage": None}})
    run.start()

    result = run.resume(REQUIREMENTS_OK)

    assert _interrupt(result)["hitl_reason"] == HitlReason.UNDECIDED


def test_revise_at_final_review_reruns_from_the_router_stage() -> None:
    run = _Run({"a09": lambda state: {"router_stage": TargetStage.FUNCTIONS}})
    run.start()
    run.resume(REQUIREMENTS_OK)

    again = run.resume({"kind": "review", "decision": "revise", "feedback": "기능 보완"})

    assert run.visited.count("a02") == 2
    assert _interrupt(again)["kind"] == "review"
    assert again["design"].revision == 1
