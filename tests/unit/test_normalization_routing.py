"""#17: 정리 실패의 생성 생략·재작업·사람 확인. 실제 LLM·DB 없이 경로를 검증한다."""

from collections.abc import Mapping
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.contracts import BranchResult, DesignState, Finding, Requirement, RunState
from specton.contracts.base import TargetStage
from specton.graph import GENERATORS, REVIEWERS, GraphState, Node, build_graph, initial_state
from specton.persistence.db import checkpoint_serde
from specton.persistence.runs import can_transition


def _design() -> DesignState:
    req = Requirement(
        id="REQ-01", source_ref={"file_format": "csv", "row": 2},
        text="입고를 등록한다", draft_text="입고를 등록한다", type="FR", analysis_version=1,
    )  # fmt: skip
    return DesignState(run_id="normalization-run", requirements=(req,))


def _finding(stage: TargetStage | None = TargetStage.DATA_MODEL) -> Finding:
    return Finding(
        id="RULE-03-1", source="rule", rule_code="RULE-03", kind="no_primary_key",
        severity="critical", targets=({"kind": "requirement", "id": "REQ-01"},),
        evidence=({"quote": "관계를 반영한 뒤에도 기본 키가 없습니다"},),
        suggestion="키를 보완한다", target_stage=stage,
        fingerprint="missing-key", iteration=0,
    )  # fmt: skip


def _failed(*, manual: bool = False, stage: TargetStage | None = TargetStage.DATA_MODEL) -> Node:
    return lambda state: {
        "normalization_failed": True,
        "requires_manual_review": manual,
        "rule_findings": (_finding(stage),),
    }


class _Run:
    def __init__(self, normalize: Node, *, max_rework: int = 3) -> None:
        self.visited: list[str] = []
        self.statuses: list[RunState] = [RunState.QUEUED]
        self.saver = InMemorySaver(serde=checkpoint_serde())
        self.config = {"configurable": {"thread_id": "normalization-run"}}
        nodes: dict[str, Node] = {}
        for name in ("a01", "a02", "a03", "a04", "rules", "export", *GENERATORS):
            nodes[name] = self._record(name, lambda state: {})
        for name in REVIEWERS:
            nodes[name] = self._record(name, self._reviewer(name))
        nodes["a09"] = self._record("a09", lambda state: {"router_stage": TargetStage.DATA_MODEL})
        nodes["normalize"] = self._record("normalize", normalize)
        self.graph = build_graph(nodes, checkpointer=self.saver, max_rework=max_rework)

    def _record(self, name: str, node: Node) -> Node:
        def recorded(state: GraphState) -> Mapping[str, Any]:
            self.visited.append(name)
            return node(state)

        return recorded

    @staticmethod
    def _reviewer(name: str) -> Node:
        return lambda state: {
            "branches": {
                name: BranchResult(branch=name, revision=state["design"].revision, ok=True)
            }
        }

    def start(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for result in self.graph.stream(
            initial_state(_design()), self.config, stream_mode="values"
        ):
            status = result["design"].status
            if status != self.statuses[-1]:
                assert can_transition(self.statuses[-1], status)
                self.statuses.append(status)
        return result


def _interrupt(result: Mapping[str, Any]) -> dict[str, Any]:
    (pending,) = result["__interrupt__"]
    return dict(pending.value)


def test_manual_failure_skips_generation_reviewers_and_automatic_router() -> None:
    run = _Run(_failed(manual=True, stage=None))

    result = run.start()

    assert _interrupt(result)["hitl_reason"] == "manual_review"
    assert result["design"].status is RunState.AWAITING_REVIEW
    assert result["design"].findings == (_finding(None),)
    assert result["design"].branch_results == {}
    assert result["failed_branches"] == ()
    assert result["rework_count"] == 0
    assert run.visited == ["a01", "a02", "a03", "a04", "normalize"]
    assert RunState.GENERATING not in run.statuses


@pytest.mark.parametrize("stage", list(TargetStage))
def test_automatic_failure_returns_to_the_target_and_clears_old_failure(stage: TargetStage) -> None:
    def normalize(state: GraphState) -> Mapping[str, Any]:
        if state["design"].revision == 0:
            return _failed(stage=stage)(state)
        return {}  # 새 반복의 성공은 과거 실패 정보가 남아 있으면 안 된다

    run = _Run(normalize)

    result = run.start()

    assert result["design"].revision == 1
    assert result["rework_count"] == 1
    assert result["normalization_failed"] is False
    assert result["requires_manual_review"] is False
    assert result["rule_findings"] == ()
    assert result["design"].findings == ()
    assert run.visited.count("normalize") == 2
    assert run.visited.count("a01") == (2 if stage is TargetStage.REQUIREMENTS else 1)
    assert run.visited.count("a02") == (1 if stage is TargetStage.DATA_MODEL else 2)
    assert run.visited.count("a03") == 2
    assert all(run.visited.count(name) == 1 for name in (*GENERATORS, *REVIEWERS, "rules"))
    assert "a09" not in run.visited
    assert _interrupt(result)["kind"] == "review"


def test_manual_failure_takes_precedence_over_an_automatic_target() -> None:
    run = _Run(_failed(manual=True))

    result = run.start()

    assert _interrupt(result)["hitl_reason"] == "manual_review"
    assert result["design"].revision == 0
    assert run.visited.count("a03") == 1


@pytest.mark.parametrize(
    ("max_rework", "reason", "attempts"), [(0, "rework_limit", 1), (3, "repeated_findings", 2)]
)
def test_automatic_failure_keeps_existing_loop_guards(
    max_rework: int, reason: str, attempts: int
) -> None:
    run = _Run(_failed(), max_rework=max_rework)

    result = run.start()

    assert _interrupt(result)["hitl_reason"] == reason
    assert run.visited.count("normalize") == attempts
    assert all(name not in run.visited for name in (*GENERATORS, *REVIEWERS, "rules", "a09"))


def test_failure_without_rule_findings_is_an_execution_error() -> None:
    run = _Run(lambda state: {"normalization_failed": True})

    with pytest.raises(ValueError, match="규칙 지적"):
        run.start()

    assert all(name not in run.visited for name in GENERATORS)


def test_normalization_exception_remains_an_execution_error() -> None:
    def broken(state: GraphState) -> Mapping[str, Any]:
        raise OSError("팩 파일을 읽을 수 없습니다")

    run = _Run(broken)

    with pytest.raises(OSError, match="팩 파일"):
        run.start()

    assert all(name not in run.visited for name in (*GENERATORS, *REVIEWERS, "a09"))


def test_direct_graph_approval_cannot_export_a_failed_normalization() -> None:
    run = _Run(_failed(manual=True))
    run.start()

    result = run.graph.invoke(
        Command(resume={"kind": "review", "decision": "approve", "feedback": ""}), run.config
    )

    assert _interrupt(result)["kind"] == "review"
    assert result["design"].status is RunState.AWAITING_REVIEW
    assert "export" not in run.visited


def test_manual_failure_survives_a_restart_and_explicit_revision_can_retry() -> None:
    run = _Run(_failed(manual=True))
    run.start()
    restarted = build_graph(
        {
            "normalize": _failed(manual=True),
            "a09": lambda state: {"router_stage": TargetStage.DATA_MODEL},
        },
        checkpointer=run.saver,
    )

    result = restarted.invoke(
        Command(resume={"kind": "review", "decision": "revise", "feedback": "사전 보완"}),
        run.config,
    )

    assert _interrupt(result)["hitl_reason"] == "manual_review"
    assert result["design"].revision == 1
    assert result["rework_count"] == 0  # 명시적 수정 요청은 자동 재작업 횟수로 세지 않는다
