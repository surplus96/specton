"""#17 실행기: lease·노드마다 저장·HITL 재개·취소·실패·시작 시 대조 (ADR-0012)."""

import threading
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any
from uuid import UUID

import pytest

from specton.config import Settings
from specton.contracts import (
    BranchResult,
    DesignState,
    Finding,
    Requirement,
    ResumeRequest,
    RunState,
    RunStatus,
    SseEventType,
)
from specton.graph import GraphState, Node, build_graph, initial_state
from specton.llm.errors import LLMRefusalError
from specton.persistence import lease
from specton.persistence.db import Pool, create_checkpointer
from specton.persistence.errors import BlockingFindingsError
from specton.persistence.runs import (
    answer_interrupt,
    create_run,
    events_after,
    get_run,
    request_cancel,
)
from specton.persistence.snapshots import get_view
from specton.runner import Runner

pytestmark = pytest.mark.db

OWNER = "owner-a"
REQUIREMENTS_OK = {"kind": "requirements", "answers": []}
APPROVE = {"kind": "review", "decision": "approve", "feedback": ""}


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        lease_seconds=5,
        lease_renew_seconds=1,
        runner_poll_seconds=0.05,
    )


class _World:
    """실행기와 그래프. 방문한 노드를 순서대로 남긴다. 새 인스턴스는 서버 재시작과 같다."""

    def __init__(
        self, pool: Pool, settings: Settings, nodes: Mapping[str, Node] | None = None
    ) -> None:
        self.pool = pool
        self.visited: list[str] = []
        recorded = {name: self._record(name, node) for name, node in (nodes or {}).items()}
        for name in ("parse", "a01", "a02", "a03"):
            recorded.setdefault(name, self._record(name, lambda state: {}))
        self.graph = build_graph(recorded, checkpointer=create_checkpointer(pool))
        self.runner = Runner(pool, self.graph, settings)

    def _record(self, name: str, node: Node) -> Node:
        def wrapped(state: GraphState) -> Mapping[str, Any]:
            self.visited.append(name)
            return node(state)

        return wrapped

    def create(self) -> UUID:
        with self.pool.connection() as conn:
            return create_run(conn, OWNER, "inventory").run_id

    def status(self, run_id: UUID) -> RunStatus:
        with self.pool.connection() as conn:
            return get_run(conn, run_id, OWNER)

    def answer(self, run_id: UUID, response: Mapping[str, Any]) -> None:
        current = self.status(run_id)
        assert current.interrupt is not None
        request = ResumeRequest.model_validate(
            {
                "interrupt_id": current.interrupt.interrupt_id,
                "expected_revision": current.revision,
                "response": dict(response),
            }
        )
        with self.pool.connection() as conn:
            answer_interrupt(conn, run_id, OWNER, request)

    def events(self, run_id: UUID) -> list[SseEventType]:
        with self.pool.connection() as conn:
            return [e.event for e in events_after(conn, run_id, OWNER, 0)]

    def status_stages(self, run_id: UUID) -> list[str | None]:
        with self.pool.connection() as conn:
            events = events_after(conn, run_id, OWNER, 0)
        return [e.data.stage for e in events if e.event is SseEventType.STATUS]

    def lease_is_live(self, run_id: UUID) -> bool:
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM job_lease WHERE run_id = %s AND lease_until > now()", (run_id,)
            ).fetchone()
        return row is not None


@pytest.fixture
def world(pool: Pool, settings: Settings) -> Iterator[Callable[..., _World]]:
    worlds: list[_World] = []

    def make(nodes: Mapping[str, Node] | None = None) -> _World:
        w = _World(pool, settings, nodes)
        worlds.append(w)
        return w

    yield make
    for w in worlds:
        w.runner.stop()


def test_queued_run_stops_at_requirements_check_and_releases_lease(
    world: Callable[..., _World],
) -> None:
    w = world()
    run_id = w.create()

    w.runner.run_pending()

    status = w.status(run_id)
    assert status.status is RunState.AWAITING_REQUIREMENTS
    assert status.interrupt is not None and status.interrupt.kind == "requirements"
    assert not w.lease_is_live(run_id)
    assert w.events(run_id)[-1] is SseEventType.INTERRUPT


def test_answers_resume_the_run_to_completion(world: Callable[..., _World]) -> None:
    w = world()
    run_id = w.create()
    w.runner.run_pending()

    w.answer(run_id, REQUIREMENTS_OK)
    w.runner.run_pending()
    review = w.status(run_id)
    w.answer(run_id, APPROVE)
    w.runner.run_pending()

    assert review.status is RunState.AWAITING_REVIEW
    assert review.interrupt is not None and review.interrupt.kind == "review"
    done = w.status(run_id)
    assert done.status is RunState.COMPLETED
    assert done.interrupt is None
    assert w.visited.count("a01") == 1  # 재개는 멈춘 곳부터
    assert w.events(run_id)[-1] is SseEventType.COMPLETED


def test_revise_asks_again_and_completes_after_approval(world: Callable[..., _World]) -> None:
    """수정 요청을 A09가 판단하지 못하면 새 확인 요청으로 다시 최종 검토를 묻는다 (#114 R3 확인)."""
    w = world()  # A09는 stub: 복귀 단계를 정하지 못한다
    run_id = w.create()
    w.runner.run_pending()
    w.answer(run_id, REQUIREMENTS_OK)
    w.runner.run_pending()
    first = w.status(run_id).interrupt

    w.answer(run_id, {"kind": "review", "decision": "revise", "feedback": "보완"})
    w.runner.run_pending()
    again = w.status(run_id)
    w.answer(run_id, APPROVE)
    w.runner.run_pending()

    assert first is not None
    assert again.status is RunState.AWAITING_REVIEW
    assert again.interrupt is not None and again.interrupt.interrupt_id != first.interrupt_id
    assert w.status(run_id).status is RunState.COMPLETED


REQ = Requirement(
    id="REQ-01",
    source_ref={"file_format": "csv", "row": 2},
    text="입고를 등록한다",
    draft_text="입고를 등록한다",
    type="FR",
    analysis_version=1,
)


def _with_requirement(state: GraphState) -> Mapping[str, Any]:
    return {"design": state["design"].evolve(requirements=(REQ,))}


def _critical_rule(state: GraphState) -> Mapping[str, Any]:
    """규칙 검사(#15) 자리. critical은 규칙 지적만 쓸 수 있다 (ADR-0010)."""
    finding = Finding.model_validate(
        {
            "id": f"RULE-01-{state['design'].iteration}-1",
            "source": "rule",
            "rule_code": "RULE-01",
            "kind": "missing_function",
            "severity": "critical",
            "targets": [{"kind": "requirement", "id": "REQ-01"}],
            "evidence": [{"req_id": "REQ-01", "quote": "입고"}],
            "suggestion": "기능을 추가한다",
            "target_stage": None,  # A09 stub이 판단하지 못해 HITL 2로 간다
            "fingerprint": "fp-critical",
            "iteration": state["design"].iteration,
        }
    )
    return {"rule_findings": (finding,)}


def test_requirements_are_saved_for_the_view_before_the_requirements_check(
    world: Callable[..., _World],
) -> None:
    """HITL 1에서 멈추기 전에 모델을 저장해 화면용 조회에 요구사항이 보인다 (#113)."""
    w = world({"a01": _with_requirement})
    run_id = w.create()

    w.runner.run_pending()

    with w.pool.connection() as conn:
        view = get_view(conn, run_id, OWNER, "requirements")
    assert w.status(run_id).status is RunState.AWAITING_REQUIREMENTS
    assert [item["id"] for item in view.items] == ["REQ-01"]


def test_findings_saved_before_final_review_block_approval(world: Callable[..., _World]) -> None:
    """HITL 2 전에 지적을 저장해야 approve가 차단 오류를 검사할 수 있다 (06 문서 resume)."""
    w = world({"a01": _with_requirement, "rules": _critical_rule})
    run_id = w.create()
    w.runner.run_pending()
    w.answer(run_id, REQUIREMENTS_OK)
    w.runner.run_pending()

    with w.pool.connection() as conn:
        view = get_view(conn, run_id, OWNER, "review")
    assert w.status(run_id).status is RunState.AWAITING_REVIEW
    assert [item["fingerprint"] for item in view.items] == ["fp-critical"]
    with pytest.raises(BlockingFindingsError):
        w.answer(run_id, APPROVE)


def test_approval_is_linked_to_the_saved_model_and_completes(
    world: Callable[..., _World],
) -> None:
    """승인은 그 revision의 저장된 모델에 연결되고, 승인 뒤 같은 모델 저장도 실패하지 않는다."""
    w = world({"a01": _with_requirement})
    run_id = w.create()
    w.runner.run_pending()
    w.answer(run_id, REQUIREMENTS_OK)
    w.runner.run_pending()

    w.answer(run_id, APPROVE)
    w.runner.run_pending()

    with w.pool.connection() as conn:
        row = conn.execute(
            "SELECT snapshot_id FROM approval WHERE run_id = %s AND decision = 'approve'",
            (run_id,),
        ).fetchone()
    assert row is not None and row["snapshot_id"] is not None
    assert w.status(run_id).status is RunState.COMPLETED


def test_failed_review_branch_is_shown_in_the_final_review_event(
    world: Callable[..., _World],
) -> None:
    """리뷰 가지가 실패해도 run은 실패하지 않고, HITL 2 이벤트에 불완전 검토를 싣는다 (TC-F14)."""

    def refuse(state: GraphState) -> Mapping[str, Any]:
        failed = BranchResult(
            branch="A06", revision=state["design"].revision, ok=False, error_code="LLM_UNAVAILABLE"
        )
        return {"branches": {"A06": failed}}

    w = world({"A06": refuse})
    run_id = w.create()
    w.runner.run_pending()
    w.answer(run_id, REQUIREMENTS_OK)

    w.runner.run_pending()

    assert w.status(run_id).status is RunState.AWAITING_REVIEW
    with w.pool.connection() as conn:
        last = events_after(conn, run_id, OWNER, 0)[-1]
    assert last.event is SseEventType.INTERRUPT
    assert last.data.payload["failed_branches"] == ["A06"]


def test_status_events_follow_each_saved_state(world: Callable[..., _World]) -> None:
    w = world()
    run_id = w.create()

    w.runner.run_pending()

    assert w.status_stages(run_id) == ["parsing", "analysing", "awaiting_requirements"]


def test_cancel_requested_during_a_node_ends_at_the_node_boundary(
    world: Callable[..., _World],
) -> None:
    holder: list[_World] = []

    def cancel_now(state: GraphState) -> Mapping[str, Any]:
        w = holder[0]
        run_id = UUID(state["design"].run_id)
        with w.pool.connection() as conn:
            request_cancel(conn, run_id, OWNER, w.status(run_id).revision)
        return {}

    w = world({"a01": cancel_now})
    holder.append(w)
    run_id = w.create()

    w.runner.run_pending()

    assert w.status(run_id).status is RunState.CANCELLED
    assert "analysing" not in w.status_stages(run_id)  # 취소된 노드 결과는 저장하지 않는다
    assert w.events(run_id)[-1] is SseEventType.CANCELLED
    assert not w.lease_is_live(run_id)


def test_node_failure_marks_the_run_failed_without_internal_details(
    world: Callable[..., _World],
) -> None:
    def refuse(state: GraphState) -> Mapping[str, Any]:
        raise LLMRefusalError("내부 프롬프트 내용")

    w = world({"a01": refuse})
    run_id = w.create()

    w.runner.run_pending()

    status = w.status(run_id)
    assert status.status is RunState.FAILED
    assert status.error is not None
    assert status.error.code == "LLM_REFUSED"
    assert status.error.retryable is False
    assert "프롬프트" not in status.error.message
    assert w.events(run_id)[-1] is SseEventType.ERROR
    assert not w.lease_is_live(run_id)


def test_a_new_runner_resumes_from_the_last_checkpoint(world: Callable[..., _World]) -> None:
    """서버 재시작: 앞 실행기가 노드 경계에서 멈추면 새 실행기가 체크포인트부터 잇는다."""
    holder: list[_World] = []

    def stop_server(state: GraphState) -> Mapping[str, Any]:
        holder[0].runner.request_stop()
        return {}

    first = world({"parse": stop_server})
    holder.append(first)
    run_id = first.create()
    first.runner.run_pending()
    assert first.status(run_id).status is RunState.PARSING
    assert not first.lease_is_live(run_id)

    restarted = world()
    restarted.runner.run_pending()

    assert restarted.status(run_id).status is RunState.AWAITING_REQUIREMENTS
    assert "parse" not in restarted.visited


def test_startup_saves_a_checkpoint_that_is_ahead_of_the_app_state(
    world: Callable[..., _World],
) -> None:
    """체크포인트는 남았는데 앱 저장 전에 죽은 경우: 그 지점의 앱 저장을 다시 한다."""
    w = world()
    run_id = w.create()
    config = {"configurable": {"thread_id": str(run_id)}}
    w.graph.invoke(
        initial_state(DesignState(run_id=str(run_id))),
        config,  # type: ignore[arg-type]
        interrupt_after=["parse"],
    )
    assert w.status(run_id).status is RunState.QUEUED

    w.runner.run_pending()

    assert w.status_stages(run_id) == ["parsing", "analysing", "awaiting_requirements"]
    assert w.status(run_id).status is RunState.AWAITING_REQUIREMENTS


def test_startup_fails_a_run_whose_checkpoint_cannot_be_matched(
    world: Callable[..., _World],
) -> None:
    """앱 상태로 맞출 수 없는 체크포인트(queued → analysing)는 `failed`로 기록한다."""
    w = world()
    run_id = w.create()
    config = {"configurable": {"thread_id": str(run_id)}}
    w.graph.invoke(
        initial_state(DesignState(run_id=str(run_id))),
        config,  # type: ignore[arg-type]
        interrupt_after=["a01"],
    )

    w.runner.run_pending()

    status = w.status(run_id)
    assert status.status is RunState.FAILED
    assert status.error is not None and status.error.code == "INTERNAL"


def test_lost_lease_stops_the_run_without_saving(world: Callable[..., _World]) -> None:
    holder: list[_World] = []

    def steal_lease(state: GraphState) -> Mapping[str, Any]:
        run_id = UUID(state["design"].run_id)
        with holder[0].pool.connection() as conn:
            conn.execute("UPDATE job_lease SET lease_until = now() WHERE run_id = %s", (run_id,))
            assert lease.acquire(conn, run_id, "other-worker", 60)
        return {}

    w = world({"a01": steal_lease})
    holder.append(w)
    run_id = w.create()

    w.runner.run_pending()

    assert w.status(run_id).status is RunState.PARSING  # a01 결과는 저장하지 않는다
    assert "wait_requirements" not in w.visited
    assert w.lease_is_live(run_id)  # 다른 실행자의 lease는 건드리지 않는다


def test_background_runner_picks_up_new_and_answered_runs(world: Callable[..., _World]) -> None:
    w = world()
    w.runner.start()
    run_id = w.create()

    _wait_for(w, run_id, RunState.AWAITING_REQUIREMENTS)
    w.answer(run_id, REQUIREMENTS_OK)
    _wait_for(w, run_id, RunState.AWAITING_REVIEW)


def test_cancel_and_lease_at_the_same_moment_never_leave_a_cancelled_run_leased(
    pool: Pool,
) -> None:
    """취소(API)와 lease 잡기(실행기)가 동시에 일어나도 취소된 run을 잡지 않는다 (#108 리뷰)."""
    for _ in range(20):
        with pool.connection() as conn:
            run_id = create_run(conn, OWNER, "inventory").run_id
        barrier = threading.Barrier(2)
        acquired: list[bool] = []

        def cancel(run_id: UUID = run_id, barrier: threading.Barrier = barrier) -> None:
            with pool.connection() as conn:
                barrier.wait()
                request_cancel(conn, run_id, OWNER, 0)

        def take(
            run_id: UUID = run_id,
            barrier: threading.Barrier = barrier,
            acquired: list[bool] = acquired,
        ) -> None:
            with pool.connection() as conn:
                barrier.wait()
                acquired.append(lease.acquire(conn, run_id, "w1", 60))

        threads = [threading.Thread(target=cancel), threading.Thread(target=take)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with pool.connection() as conn:
            final = get_run(conn, run_id, OWNER).status
        if final is RunState.CANCELLED:
            assert acquired == [False]
        else:
            assert final is RunState.CANCEL_REQUESTED
            assert acquired == [True]


def _wait_for(w: _World, run_id: UUID, status: RunState, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if w.status(run_id).status is status:
            return
        time.sleep(0.05)
    raise AssertionError(f"{status}에 도달하지 못했습니다: {w.status(run_id).status}")
