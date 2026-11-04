"""실행기: 전용 스레드 풀에서 설계 그래프를 돌리고 앱 상태를 저장한다 (ADR-0012, #17).

- 시작할 때와 `runner_poll_seconds`마다 `lease.claimable_runs`를 찾아 lease를 잡고 실행한다.
  동시 실행 수는 `run_concurrency`다.
- lease는 노드와 별개로 `lease_renew_seconds`마다 갱신한다.
  잃으면 그 실행을 멈추고 더 저장하지 않는다.
- 노드가 끝날 때마다 체크포인트 기준으로 `runs.record_progress`에 저장한다(멱등).
  같은 트랜잭션에서 `snapshots.save_model`로 모델·지적을 남겨 화면용 조회가 읽는다(#113).
  노드는 DB에 쓰지 않는다.
- 사람 확인에서 멈추면 대기 상태와 interrupt를 저장하고 lease를 반납한다.
  답은 approval에서 읽어 재개한다.
- 취소는 노드 경계에서 확인한다. 그 노드의 결과는 저장하지 않고 `cancelled`로 끝낸다.
- DB 연결은 저장·확인할 때만 짧게 빌린다. 노드(LLM 호출)가 도는 동안에는 잡지 않는다.
"""

import logging
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot

from specton.config import Settings
from specton.contracts import (
    DesignState,
    Error,
    ErrorCode,
    Interrupt,
    InterruptKind,
    RunState,
    RunStatus,
)
from specton.contracts import SseEventType as E
from specton.graph import GraphState, initial_state
from specton.llm.errors import LLMError
from specton.persistence import lease, runs, snapshots
from specton.persistence.db import Pool
from specton.persistence.errors import InvalidTransitionError, LeaseLostError
from specton.persistence.lease import WAITING_STATES
from specton.persistence.runs import NewEvent

logger = logging.getLogger(__name__)
S = RunState

Graph = CompiledStateGraph[GraphState, None, GraphState, GraphState]

# 06 문서 오류 표의 "다시 시도". 실패 원인 메시지에는 내부 예외 내용을 넣지 않는다.
_RETRYABLE = frozenset(
    {ErrorCode.LLM_OUTPUT_INVALID, ErrorCode.LLM_UNAVAILABLE, ErrorCode.INTERNAL}
)
_ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.LLM_REFUSED: "모델이 응답을 거절했습니다. 입력을 확인해 주세요.",
    ErrorCode.LLM_OUTPUT_INVALID: "모델 출력이 형식에 맞지 않습니다. 다시 시도해 주세요.",
    ErrorCode.LLM_UNAVAILABLE: "모델을 호출하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    ErrorCode.BUDGET_EXCEEDED: "실행 예산을 넘었습니다. 입력을 줄여 다시 시도해 주세요.",
    ErrorCode.EXTRACTION_FAILED: "문서를 읽지 못했습니다. 다른 파일로 다시 시도해 주세요.",
    ErrorCode.INTERNAL: "실행 중 서버 오류가 발생했습니다.",
}
_INTERRUPT_MESSAGES: dict[InterruptKind, str] = {
    InterruptKind.EXTRACTION: "추출 결과 확인이 필요합니다",
    InterruptKind.REQUIREMENTS: "요구사항 확인이 필요합니다",
    InterruptKind.REVIEW: "최종 검토가 필요합니다",
}
_STATUS_MESSAGES: dict[RunState, str] = {
    S.PARSING: "문서를 읽고 있습니다",
    S.AWAITING_INPUT: "추출 결과 확인을 기다립니다",
    S.ANALYSING: "요구사항을 분석하고 있습니다",
    S.AWAITING_REQUIREMENTS: "요구사항 확인을 기다립니다",
    S.DESIGNING: "설계 모델을 만들고 있습니다",
    S.GENERATING: "산출물을 만들고 있습니다",
    S.REVIEWING: "설계를 검토하고 있습니다",
    S.AWAITING_REVIEW: "최종 검토를 기다립니다",
    S.EXPORTING: "산출물을 내보내고 있습니다",
    S.COMPLETED: "설계를 완료했습니다",
}


class _Stop(Exception):
    """이 실행자는 여기서 멈춘다 (lease 상실·서버 종료). 더 저장하지 않고 lease만 반납한다."""


class _Cancelled(Exception):
    """노드 경계에서 취소 요청을 확인했다."""


class Runner:
    """run을 찾아 실행하는 실행기. API 프로세스에 하나만 둔다 (`--workers 1`, ADR-0012)."""

    def __init__(
        self, pool: Pool, graph: Graph, settings: Settings, *, holder: str | None = None
    ) -> None:
        self.pool = pool
        self.graph = graph
        self.settings = settings
        self.holder = holder or f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
        self._stopping = threading.Event()
        self._active: set[UUID] = set()
        self._lock = threading.Lock()
        self._workers: ThreadPoolExecutor | None = None
        self._poller: threading.Thread | None = None

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    def start(self) -> None:
        """스레드 풀과 주기 조회를 시작한다."""
        self._workers = ThreadPoolExecutor(
            self.settings.run_concurrency, thread_name_prefix="specton-run"
        )
        self._poller = threading.Thread(target=self._poll_loop, name="specton-runner", daemon=True)
        self._poller.start()

    def request_stop(self) -> None:
        """새 run을 잡지 않고, 실행 중인 run은 다음 노드 경계에서 저장한 뒤 멈춘다."""
        self._stopping.set()

    def stop(self) -> None:
        """멈추고 실행 중인 run이 노드 경계까지 끝나기를 기다린다.

        반납한 run은 다음 기동 때 마지막 체크포인트부터 잇는다.
        """
        self.request_stop()
        if self._poller is not None:
            self._poller.join()
            self._poller = None
        if self._workers is not None:
            self._workers.shutdown(wait=True)
            self._workers = None

    def run_pending(self) -> None:
        """잡을 수 있는 run을 지금 스레드에서 차례로 실행한다 (점검·테스트용)."""
        while not self.stopping and (claimed := self._claim(1)):
            self._execute(claimed[0])

    def _poll_loop(self) -> None:
        while not self.stopping:
            try:
                self._dispatch()
            except Exception:
                logger.exception("실행할 run을 찾지 못했습니다")
            self._stopping.wait(self.settings.runner_poll_seconds)

    def _dispatch(self) -> None:
        with self._lock:
            free = self.settings.run_concurrency - len(self._active)
        if free <= 0 or self._workers is None:
            return
        for run_id in self._claim(free):
            self._workers.submit(self._execute, run_id)

    def _claim(self, limit: int) -> list[UUID]:
        """`queued`·lease 만료 run의 lease를 잡는다. 잡은 run은 실행 중 목록에 넣는다."""
        claimed: list[UUID] = []
        with self.pool.connection() as conn:
            for run_id in lease.claimable_runs(conn, limit):
                with self._lock:
                    if run_id in self._active:
                        continue
                if lease.acquire(conn, run_id, self.holder, self.settings.lease_seconds):
                    with self._lock:
                        self._active.add(run_id)
                    claimed.append(run_id)
        return claimed

    def _execute(self, run_id: UUID) -> None:
        lost, finished = threading.Event(), threading.Event()
        renewer = threading.Thread(
            target=self._renew, args=(run_id, lost, finished), name=f"lease-{run_id}", daemon=True
        )
        renewer.start()
        try:
            _Job(self, run_id, lost).run()
        except LeaseLostError:
            logger.warning("run %s의 lease를 잃어 저장하지 않고 멈춥니다", run_id)
        except Exception:
            logger.exception("run %s 실행 중 처리하지 못한 오류", run_id)
        finally:
            finished.set()
            renewer.join()
            with self.pool.connection() as conn:
                lease.release(conn, run_id, self.holder)  # 잃은 lease면 아무것도 하지 않는다
            with self._lock:
                self._active.discard(run_id)

    def _renew(self, run_id: UUID, lost: threading.Event, finished: threading.Event) -> None:
        """노드와 별개로 lease를 갱신한다. 긴 LLM 호출 중 만료되어 실행자가 둘이 되지 않게 한다."""
        while not finished.wait(self.settings.lease_renew_seconds):
            try:
                with self.pool.connection() as conn:
                    lease.renew(conn, run_id, self.holder, self.settings.lease_seconds)
            except LeaseLostError:
                lost.set()
                return
            except Exception:
                logger.exception("run %s lease 갱신 실패. 다음 주기에 다시 시도합니다", run_id)


class _Job:
    """run 하나의 실행. lease를 잡은 실행기 스레드에서만 돈다."""

    def __init__(self, runner: Runner, run_id: UUID, lost: threading.Event) -> None:
        self.runner = runner
        self.run_id = run_id
        self.lost = lost
        self.config: RunnableConfig = {"configurable": {"thread_id": str(run_id)}}
        self.status = S.QUEUED  # 마지막으로 저장한 run 상태

    def run(self) -> None:
        graph = self.runner.graph
        try:
            self.status = self._load().status
            if self.status is S.CANCEL_REQUESTED:
                raise _Cancelled
            start = self._start_input()
            for _ in graph.stream(start, self.config, stream_mode="updates", durability="sync"):
                self._at_boundary()
                snapshot = graph.get_state(self.config)
                if not snapshot.interrupts:
                    self._save(snapshot)
                if self.runner.stopping:
                    raise _Stop  # 서버 종료: 끝난 노드까지 저장하고 멈춘다
            self._settle(graph.get_state(self.config))
        except _Stop:
            return
        except _Cancelled:
            self._end(S.CANCELLED, NewEvent(E.CANCELLED, "실행을 취소했습니다", stage="cancelled"))
        except LeaseLostError:
            raise
        except Exception as exc:
            self._fail(exc)

    def _at_boundary(self) -> None:
        """노드 경계 확인. lease를 잃었거나 취소 요청이면 이 노드 결과를 저장하지 않는다."""
        if self.lost.is_set():
            raise _Stop
        if self._load().status is S.CANCEL_REQUESTED:
            raise _Cancelled

    def _start_input(self) -> GraphState | Command[Any] | None:
        """처음이면 초기 상태, 사람 확인에 답이 왔으면 그 답, 아니면 마지막 체크포인트부터.

        체크포인트가 앱 저장보다 앞서 있으면 그 지점의 앱 저장을 먼저 다시 한다 (시작 시 대조).
        """
        snapshot = self.runner.graph.get_state(self.config)
        if not snapshot.values:
            return initial_state(DesignState(run_id=str(self.run_id)))
        if _checkpoint_id(snapshot) != self._saved_checkpoint():
            if snapshot.interrupts:
                self._pause(snapshot)
                raise _Stop
            self._save(snapshot)
        if snapshot.interrupts:
            (pending,) = snapshot.interrupts
            with self.runner.pool.connection() as conn:
                answer = runs.answer_for(conn, self.run_id, pending.id)
            if answer is None:
                raise RuntimeError(f"확인 요청 {pending.id}의 응답이 없는데 실행 가능 상태입니다")
            return Command(resume=answer)
        if not snapshot.next:
            raise _Stop  # 그래프가 이미 끝났고 앱 저장도 맞췄다
        return None

    def _settle(self, snapshot: StateSnapshot) -> None:
        """그래프가 멈추거나 끝난 뒤의 저장."""
        if snapshot.interrupts:
            self._pause(snapshot)
        else:
            self._save(snapshot)

    def _save(self, snapshot: StateSnapshot) -> None:
        design: DesignState = snapshot.values["design"]
        if design.status in WAITING_STATES:
            return  # 대기 상태는 멈출 때 interrupt와 함께 저장한다
        events = self._status_events(design.status)
        if design.status is S.COMPLETED:
            events.append(NewEvent(E.COMPLETED, "설계를 완료했습니다", stage=design.status.value))
        self._record(_checkpoint_id(snapshot), design, events=events)

    def _pause(self, snapshot: StateSnapshot) -> None:
        """사람 확인 대기: 대기 상태와 interrupt를 저장한다. lease는 실행이 끝나면 반납한다."""
        (pending,) = snapshot.interrupts  # 확인 노드는 한 번에 하나만 멈춘다
        value: dict[str, Any] = pending.value
        kind = InterruptKind(value["kind"])
        design: DesignState = snapshot.values["design"]
        interrupt = Interrupt(interrupt_id=pending.id, kind=kind, message=_INTERRUPT_MESSAGES[kind])
        payload = {"interrupt_id": pending.id, "kind": kind.value}
        if value.get("hitl_reason"):
            payload["hitl_reason"] = str(value["hitl_reason"])
        events = self._status_events(design.status)
        events.append(
            NewEvent(E.INTERRUPT, interrupt.message, stage=design.status.value, payload=payload)
        )
        self._record(_checkpoint_id(snapshot), design, interrupt=interrupt, events=events)

    def _status_events(self, status: RunState) -> list[NewEvent]:
        if status is self.status:
            return []
        message = _STATUS_MESSAGES.get(status, "진행 상태가 바뀌었습니다")
        return [NewEvent(E.STATUS, message, stage=status.value)]

    def _record(
        self,
        checkpoint_id: str,
        design: DesignState,
        *,
        interrupt: Interrupt | None = None,
        events: list[NewEvent],
    ) -> None:
        """진행과 모델을 한 트랜잭션으로 저장한다.

        사람 확인에서 멈출 때도 여기를 거치므로, 확인 요청 전에 그 revision 모델이 저장된다.
        resume API의 approve가 이 모델에 연결되고 차단 오류를 검사한다.
        """
        try:
            with self.runner.pool.connection() as conn, conn.transaction():
                saved = runs.record_progress(
                    conn,
                    self.run_id,
                    self.runner.holder,
                    checkpoint_id,
                    status=design.status,
                    revision=design.revision,
                    iteration=design.iteration,
                    stage=design.status.value,
                    interrupt=interrupt,
                    events=events,
                )
                if saved is not None:  # 같은 체크포인트를 다시 저장하면 모델도 이미 있다
                    snapshots.save_model(conn, self.run_id, self.runner.holder, design)
        except InvalidTransitionError:
            if self._load().status is S.CANCEL_REQUESTED:
                raise _Cancelled from None  # 저장 직전에 취소 요청이 들어왔다
            raise
        self.status = design.status

    def _fail(self, exc: Exception) -> None:
        logger.error("run %s 실패", self.run_id, exc_info=exc)
        code = ErrorCode(exc.code) if isinstance(exc, LLMError) else ErrorCode.INTERNAL
        error = Error(
            code=code.value,
            message=_ERROR_MESSAGES[code],
            run_id=str(self.run_id),
            retryable=code in _RETRYABLE,
        )
        payload = {"code": code.value, "retryable": error.retryable}
        event = NewEvent(E.ERROR, error.message, stage="failed", payload=payload)
        self._end(S.FAILED, event, error)

    def _end(self, status: RunState, event: NewEvent, error: Error | None = None) -> None:
        """취소·실패로 끝낸다. 진행 중이던 노드 결과는 저장하지 않는다."""
        current = self._load()
        checkpoint = _checkpoint_id(self.runner.graph.get_state(self.config))
        with self.runner.pool.connection() as conn:
            runs.record_progress(
                conn,
                self.run_id,
                self.runner.holder,
                f"{status.value}:{checkpoint}",  # 같은 체크포인트의 진행 저장과 멱등 키를 나눈다
                status=status,
                revision=current.revision,
                error=error,
                events=[event],
            )

    def _load(self) -> RunStatus:
        with self.runner.pool.connection() as conn:
            return runs.load_run(conn, self.run_id)

    def _saved_checkpoint(self) -> str | None:
        with self.runner.pool.connection() as conn, conn.transaction():
            return lease.check_holder(conn, self.run_id, self.runner.holder)


def _checkpoint_id(snapshot: StateSnapshot) -> str:
    configurable = snapshot.config.get("configurable", {}) if snapshot.config else {}
    return str(configurable.get("checkpoint_id") or "start")
