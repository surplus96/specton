"""작업 lease: run당 실행자를 1개로 제한한다 (ADR-0012).

시각은 모두 DB의 `now()`를 쓴다. 반납은 행을 지우지 않고 만료시켜 `last_checkpoint`를 남긴다.
실행기 루프·갱신 주기·재개는 R1(#17)이 이 함수들로 만든다.
"""

from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from specton.contracts import RunState
from specton.persistence.errors import LeaseLostError

# 실행자가 없는 대기 상태. 이 상태의 run은 lease를 잡지 않는다 (HITL 대기 중 반납).
WAITING_STATES = frozenset(
    {RunState.AWAITING_INPUT, RunState.AWAITING_REQUIREMENTS, RunState.AWAITING_REVIEW}
)
FINAL_STATES = frozenset({RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED})
# lease를 잡아 실행할 수 있는 상태
RUNNABLE_STATES = frozenset(RunState) - WAITING_STATES - FINAL_STATES

_RUNNABLE = [s.value for s in RUNNABLE_STATES]


def acquire(conn: Connection[DictRow], run_id: UUID, holder: str, seconds: int) -> bool:
    """lease를 잡는다. 실행할 수 없는 상태이거나 다른 실행자가 살아 있으면 False.

    run 행을 FOR SHARE로 잠가, 같은 순간 API가 취소로 끝낸 run을 잡지 않는다.
    """
    row = conn.execute(
        """
        INSERT INTO job_lease AS l (run_id, holder, lease_until)
        SELECT r.run_id, %(holder)s, now() + make_interval(secs => %(seconds)s)
        FROM run r WHERE r.run_id = %(run_id)s AND r.status = ANY(%(runnable)s)
        FOR SHARE OF r
        ON CONFLICT (run_id) DO UPDATE
            SET holder = EXCLUDED.holder, lease_until = EXCLUDED.lease_until
            WHERE l.lease_until <= now() OR l.holder = EXCLUDED.holder
        RETURNING run_id
        """,
        {"run_id": run_id, "holder": holder, "seconds": seconds, "runnable": _RUNNABLE},
    ).fetchone()
    return row is not None


def renew(conn: Connection[DictRow], run_id: UUID, holder: str, seconds: int) -> None:
    """lease를 연장한다. 이미 만료됐거나 다른 실행자에게 넘어갔으면 LeaseLostError."""
    row = conn.execute(
        """
        UPDATE job_lease SET lease_until = now() + make_interval(secs => %(seconds)s)
        WHERE run_id = %(run_id)s AND holder = %(holder)s AND lease_until > now()
        RETURNING run_id
        """,
        {"run_id": run_id, "holder": holder, "seconds": seconds},
    ).fetchone()
    if row is None:
        raise LeaseLostError(f"run {run_id}의 lease를 잃었습니다")


def release(conn: Connection[DictRow], run_id: UUID, holder: str) -> None:
    """lease를 반납한다(HITL 대기·종료). 이미 잃은 lease면 아무것도 하지 않는다."""
    conn.execute(
        "UPDATE job_lease SET lease_until = now() WHERE run_id = %s AND holder = %s",
        (run_id, holder),
    )


def claimable_runs(conn: Connection[DictRow], limit: int) -> list[UUID]:
    """실행자를 기다리는 run: `queued`와, 실행 중 상태인데 lease가 없거나 만료된 것. 오래된 순."""
    rows = conn.execute(
        """
        SELECT r.run_id FROM run r LEFT JOIN job_lease l USING (run_id)
        WHERE r.status = ANY(%(runnable)s) AND (l.run_id IS NULL OR l.lease_until <= now())
        ORDER BY r.created_at LIMIT %(limit)s
        """,
        {"runnable": _RUNNABLE, "limit": limit},
    ).fetchall()
    return [row["run_id"] for row in rows]


def check_holder(conn: Connection[DictRow], run_id: UUID, holder: str) -> str | None:
    """저장 트랜잭션 안에서 lease 행을 잠그고 확인한다. 마지막 체크포인트를 돌려준다.

    lease를 잃었으면 LeaseLostError. 호출하는 쪽이 트랜잭션을 열어 둔다.
    """
    row = conn.execute(
        """
        SELECT last_checkpoint FROM job_lease
        WHERE run_id = %s AND holder = %s AND lease_until > now()
        FOR UPDATE
        """,
        (run_id, holder),
    ).fetchone()
    if row is None:
        raise LeaseLostError(f"run {run_id}의 lease를 잃어 기록하지 않습니다")
    last: str | None = row["last_checkpoint"]
    return last
