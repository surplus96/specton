"""run 저장: 생성·조회·진행 기록·재개·취소 (05 문서 "플랫폼 저장", ADR-0012).

진행 기록은 run 상태·revision·run_event·holder 확인을 한 트랜잭션으로 묶는다.
잠금 순서는 항상 run → job_lease다.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from specton.contracts import (
    Contract,
    Error,
    Interrupt,
    InterruptKind,
    ResumeRequest,
    RunState,
    RunStatus,
    RunSummary,
    SseEvent,
    SseEventData,
    SseEventType,
)
from specton.persistence.errors import (
    BlockingFindingsError,
    EventReplayExpiredError,
    InterruptStaleError,
    InvalidTransitionError,
    ResponseMismatchError,
    RevisionConflictError,
    RunNotFoundError,
)
from specton.persistence.lease import FINAL_STATES, WAITING_STATES, check_holder

S = RunState

# 상태도(03 문서). 실패·취소 요청은 끝나지 않은 어느 상태에서든 갈 수 있다.
_FLOW: Mapping[RunState, frozenset[RunState]] = {
    S.QUEUED: frozenset({S.PARSING}),
    S.PARSING: frozenset({S.AWAITING_INPUT, S.ANALYSING}),
    S.AWAITING_INPUT: frozenset({S.ANALYSING}),
    S.ANALYSING: frozenset({S.AWAITING_REQUIREMENTS}),
    S.AWAITING_REQUIREMENTS: frozenset({S.DESIGNING}),
    # 요구사항 단계로 재작업하면 A01로 돌아간다 (03 문서 재작업 복귀, #111)
    S.DESIGNING: frozenset({S.GENERATING, S.ANALYSING}),
    S.GENERATING: frozenset({S.REVIEWING}),
    S.REVIEWING: frozenset({S.DESIGNING, S.AWAITING_REVIEW, S.ANALYSING}),
    S.AWAITING_REVIEW: frozenset({S.DESIGNING, S.EXPORTING}),
    S.EXPORTING: frozenset({S.COMPLETED}),
    S.CANCEL_REQUESTED: frozenset({S.CANCELLED}),
}


def can_transition(current: RunState, new: RunState) -> bool:
    """상태 전이 검사. 같은 상태 유지(revision·iteration만 갱신)는 진행 중인 run에서 허용한다.

    취소 요청 중인 run은 `cancelled`나 `failed`로만 끝낸다. 진행 결과를 더 올리지 않는다.
    """
    if current in FINAL_STATES:
        return False
    if current is S.CANCEL_REQUESTED:
        return new in (S.CANCELLED, S.FAILED)
    if new is current or new in (S.FAILED, S.CANCEL_REQUESTED):
        return True
    return new in _FLOW.get(current, frozenset())


@dataclass(frozen=True)
class NewEvent:
    """기록할 SSE 이벤트. `run_id`·`revision`·`id`는 저장할 때 채운다."""

    event: SseEventType
    message: str
    stage: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def create_run(
    conn: Connection[DictRow],
    owner_ref: str,
    pack: str,
    *,
    pack_version: str | None = None,
    model_config: Mapping[str, Any] | None = None,
    run_id: UUID | None = None,
) -> RunStatus:
    """`queued` 상태의 run을 만든다. 실행기가 `claimable_runs`로 찾아간다.

    `run_id`를 주면 그 값을 쓴다 (업로드 파일을 run별 위치에 먼저 저장할 때).
    """
    row = conn.execute(
        """
        INSERT INTO run (run_id, owner_ref, status, pack, pack_version, model_config)
        VALUES (%s, %s, 'queued', %s, %s, %s)
        RETURNING run_id, status, revision
        """,
        (run_id or uuid4(), owner_ref, pack, pack_version, Jsonb(dict(model_config or {}))),
    ).fetchone()
    assert row is not None
    return RunStatus(run_id=row["run_id"], status=row["status"], revision=row["revision"])


def add_document(
    conn: Connection[DictRow],
    run_id: UUID,
    *,
    document_id: UUID,
    file_name: str,
    file_format: str,
    file_hash: str,
    storage_ref: str,
) -> None:
    """업로드 문서를 run에 연결한다. `storage_ref`는 저장소 안 위치이며 응답에 넣지 않는다."""
    conn.execute(
        """
        INSERT INTO document (document_id, run_id, file_name, file_format, file_hash, storage_ref)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (document_id, run_id, file_name, file_format, file_hash, storage_ref),
    )


def get_run(conn: Connection[DictRow], run_id: UUID, owner_ref: str) -> RunStatus:
    """소유자의 run 상태. 없거나 다른 소유자면 RunNotFoundError (ADR-0011)."""
    row = conn.execute(
        """
        SELECT run_id, status, revision, stage, interrupt, error FROM run
        WHERE run_id = %s AND owner_ref = %s
        """,
        (run_id, owner_ref),
    ).fetchone()
    if row is None:
        raise RunNotFoundError(str(run_id))
    return RunStatus.model_validate(row)


def list_runs(
    conn: Connection[DictRow], owner_ref: str, *, status: RunState | None = None, limit: int = 50
) -> list[RunSummary]:
    """소유자의 run 목록. 최근 것부터."""
    rows = conn.execute(
        """
        SELECT run_id, status, revision, created_at FROM run
        WHERE owner_ref = %(owner)s AND (%(status)s::text IS NULL OR status = %(status)s)
        ORDER BY created_at DESC LIMIT %(limit)s
        """,
        {"owner": owner_ref, "status": status, "limit": limit},
    ).fetchall()
    return [RunSummary.model_validate(row) for row in rows]


def record_progress(
    conn: Connection[DictRow],
    run_id: UUID,
    holder: str,
    checkpoint_id: str,
    *,
    status: RunState,
    revision: int,
    iteration: int | None = None,
    stage: str | None = None,
    interrupt: Interrupt | None = None,
    error: Error | None = None,
    events: Sequence[NewEvent] = (),
) -> list[SseEvent] | None:
    """노드가 끝난 뒤 실행기가 앱 상태를 저장한다 (ADR-0012).

    run 상태·revision·이벤트를 한 트랜잭션으로 쓰고, lease를 가진 실행자만 쓸 수 있다.
    같은 체크포인트를 다시 저장하면 아무것도 하지 않고 None을 돌려준다(멱등).
    `interrupt`는 사람 확인 대기 상태에서만, `error`는 `failed`에서만 준다.
    """
    if (interrupt is not None) != (status in WAITING_STATES):
        raise ValueError("interrupt는 사람 확인 대기 상태에서만, 그때는 반드시 줍니다")
    if error is not None and status is not S.FAILED:
        raise ValueError("error는 failed 상태에서만 줍니다")
    with conn.transaction():
        current = _lock_run(conn, run_id)
        if check_holder(conn, run_id, holder) == checkpoint_id:
            return None
        if not can_transition(current["status"], status):
            raise InvalidTransitionError(f"{current['status']} → {status}")
        conn.execute(
            """
            UPDATE run SET status = %s, revision = %s, iteration = COALESCE(%s, iteration),
                stage = %s, interrupt = %s, error = %s, updated_at = now()
            WHERE run_id = %s
            """,
            (status, revision, iteration, stage, _json(interrupt), _json(error), run_id),
        )
        saved = _append_events(conn, run_id, revision, events)
        conn.execute(
            "UPDATE job_lease SET last_checkpoint = %s WHERE run_id = %s",
            (checkpoint_id, run_id),
        )
    return saved


def request_cancel(
    conn: Connection[DictRow], run_id: UUID, owner_ref: str, expected_revision: int
) -> tuple[RunState, list[SseEvent]]:
    """취소 요청 (ADR-0012 "취소").

    실행자가 있으면 `cancel_requested`와 status 이벤트를 남기고 실행기가 노드 경계에서 끝낸다.
    `queued`·HITL 대기처럼 실행자가 없으면 바로 `cancelled`와 cancelled 이벤트로 끝낸다.
    이미 취소 요청 중이면 그대로 돌려주고, 끝난 run이면 InvalidTransitionError.
    """
    with conn.transaction():
        current = _lock_run(conn, run_id, owner_ref)
        state: RunState = current["status"]
        if current["revision"] != expected_revision:
            raise RevisionConflictError(str(run_id), current["revision"])
        if state is S.CANCEL_REQUESTED:
            return state, []
        if state in FINAL_STATES:
            raise InvalidTransitionError(f"이미 끝난 실행입니다: {state}")
        if state in WAITING_STATES or not _has_live_lease(conn, run_id):
            new, event = S.CANCELLED, NewEvent(SseEventType.CANCELLED, "실행을 취소했습니다")
        else:
            new, event = S.CANCEL_REQUESTED, NewEvent(SseEventType.STATUS, "취소 처리 중입니다")
        conn.execute(
            "UPDATE run SET status = %s, interrupt = NULL, updated_at = now() WHERE run_id = %s",
            (new, run_id),
        )
        events = _append_events(conn, run_id, current["revision"], [event])
    return new, events


# 사람 확인 지점 → 답을 받은 뒤 상태 (03 문서 상태도). review는 결정에 따라 달라진다.
_AFTER_ANSWER: Mapping[InterruptKind, RunState] = {
    InterruptKind.EXTRACTION: S.ANALYSING,
    InterruptKind.REQUIREMENTS: S.DESIGNING,
}
_AFTER_REVIEW: Mapping[str, RunState | None] = {
    "approve": S.EXPORTING,
    "revise": S.DESIGNING,
    "hold": None,  # 보류: 같은 확인 요청으로 계속 기다린다
}


def answer_interrupt(
    conn: Connection[DictRow], run_id: UUID, owner_ref: str, request: ResumeRequest
) -> tuple[RunState, list[SseEvent]]:
    """사람 확인 응답을 받아 실행을 재개한다 (06 문서 `resume`).

    같은 확인 요청에는 한 번만 답할 수 있다. 오래되었거나 이미 답한 요청이면 InterruptStaleError,
    revision이 다르면 RevisionConflictError. 답을 받으면 실행 가능한 상태로 바꿔 실행기가
    lease를 잡아 이어 간다. 보류(hold)는 기록만 하고 계속 기다린다.
    """
    response = request.response
    with conn.transaction():
        current = _lock_run(conn, run_id, owner_ref)
        if current["revision"] != request.expected_revision:
            raise RevisionConflictError(str(run_id), current["revision"])
        interrupt = current["interrupt"]
        if (
            current["status"] not in WAITING_STATES
            or interrupt is None
            or interrupt["interrupt_id"] != request.interrupt_id
        ):
            raise InterruptStaleError(request.interrupt_id)
        if interrupt["kind"] != response.kind:
            raise ResponseMismatchError(f"{interrupt['kind']} 확인에 {response.kind} 응답")
        if response.kind == "extraction":
            new: RunState | None = _AFTER_ANSWER[InterruptKind.EXTRACTION]
            if not response.confirmed:
                new = S.CANCELLED  # 확인하지 않으면 중단한다 (#95 결론에 따라 바뀔 수 있음)
            decision = "confirm" if response.confirmed else "stop"
        elif response.kind == "requirements":
            new, decision = _AFTER_ANSWER[InterruptKind.REQUIREMENTS], "answer"
        else:
            new, decision = _AFTER_REVIEW[response.decision], response.decision
            if decision == "approve" and _has_blocking_findings(conn, run_id, current["revision"]):
                raise BlockingFindingsError(str(run_id))
        if new is None:
            events = _append_events(
                conn, run_id, current["revision"], [NewEvent(SseEventType.STATUS, "보류했습니다")]
            )
            return current["status"], events
        conn.execute(
            """
            INSERT INTO approval (approval_id, run_id, snapshot_id, interrupt_id, actor_ref,
                decision, feedback, response)
            VALUES (%s, %s, (SELECT snapshot_id FROM model_snapshot
                             WHERE run_id = %s AND revision = %s), %s, %s, %s, %s, %s)
            """,
            (
                uuid4(), run_id, run_id, current["revision"], request.interrupt_id, owner_ref,
                decision, getattr(response, "feedback", ""), _json(response),
            ),
        )  # fmt: skip
        conn.execute(
            "UPDATE run SET status = %s, interrupt = NULL, updated_at = now() WHERE run_id = %s",
            (new, run_id),
        )
        if new is S.CANCELLED:
            event = NewEvent(SseEventType.CANCELLED, "추출 확인을 중단했습니다")
        else:
            event = NewEvent(SseEventType.STATUS, "답변을 받아 다시 진행합니다", stage=new.value)
        events = _append_events(conn, run_id, current["revision"], [event])
    return new, events


def events_after(
    conn: Connection[DictRow], run_id: UUID, owner_ref: str, after_id: int, limit: int = 500
) -> list[SseEvent]:
    """SSE 재생용: `after_id`보다 큰 이벤트를 순서대로. 짧게 읽고 연결을 돌려준다.

    소유자를 함께 검사한다. 없거나 다른 소유자의 run이면 RunNotFoundError (ADR-0011).
    아직 없는 이벤트 ID를 기준으로 재생을 요청하면 EventReplayExpiredError(상태를 다시 조회).
    """
    row = conn.execute(
        "SELECT last_event_id FROM run WHERE run_id = %s AND owner_ref = %s",
        (run_id, owner_ref),
    ).fetchone()
    if row is None:
        raise RunNotFoundError(str(run_id))
    if after_id > row["last_event_id"]:
        raise EventReplayExpiredError(str(run_id))
    rows = conn.execute(
        """
        SELECT event_id, event_type, payload FROM run_event
        WHERE run_id = %s AND event_id > %s ORDER BY event_id LIMIT %s
        """,
        (run_id, after_id, limit),
    ).fetchall()
    return [
        SseEvent(id=r["event_id"], event=r["event_type"], data=SseEventData(**r["payload"]))
        for r in rows
    ]


def _lock_run(
    conn: Connection[DictRow], run_id: UUID, owner_ref: str | None = None
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT status, revision, interrupt FROM run
        WHERE run_id = %(run_id)s AND (%(owner)s::text IS NULL OR owner_ref = %(owner)s)
        FOR UPDATE
        """,
        {"run_id": run_id, "owner": owner_ref},
    ).fetchone()
    if row is None:
        raise RunNotFoundError(str(run_id))
    return {**row, "status": RunState(row["status"])}


def _has_blocking_findings(conn: Connection[DictRow], run_id: UUID, revision: int) -> bool:
    """현재 revision 모델에 차단 오류(critical, ADR-0010)가 남아 있는지."""
    row = conn.execute(
        """
        SELECT 1 FROM finding f JOIN model_snapshot s USING (snapshot_id)
        WHERE s.run_id = %s AND s.revision = %s AND f.payload->>'severity' = 'critical'
        LIMIT 1
        """,
        (run_id, revision),
    ).fetchone()
    return row is not None


def _json(model: Contract | None) -> Jsonb | None:
    return None if model is None else Jsonb(model.model_dump(mode="json"))


def _has_live_lease(conn: Connection[DictRow], run_id: UUID) -> bool:
    row = conn.execute(
        "SELECT 1 FROM job_lease WHERE run_id = %s AND lease_until > now()", (run_id,)
    ).fetchone()
    return row is not None


def _append_events(
    conn: Connection[DictRow], run_id: UUID, revision: int, events: Sequence[NewEvent]
) -> list[SseEvent]:
    """run의 `last_event_id`로 이벤트 ID를 이어서 발급한다. run 행이 잠긴 상태에서 부른다."""
    if not events:
        return []
    row = conn.execute(
        "UPDATE run SET last_event_id = last_event_id + %s WHERE run_id = %s "
        "RETURNING last_event_id",
        (len(events), run_id),
    ).fetchone()
    assert row is not None
    first = row["last_event_id"] - len(events) + 1
    saved: list[SseEvent] = []
    for event_id, e in enumerate(events, start=first):
        data = SseEventData(
            run_id=str(run_id),
            revision=revision,
            stage=e.stage,
            message=e.message,
            payload=e.payload,
        )
        conn.execute(
            "INSERT INTO run_event (run_id, event_id, event_type, revision, payload) "
            "VALUES (%s, %s, %s, %s, %s)",
            (run_id, event_id, e.event, revision, Jsonb(data.model_dump(mode="json"))),
        )
        saved.append(SseEvent(id=event_id, event=e.event, data=data))
    return saved
