"""플랫폼 저장·lease·취소 (ADR-0012). 로컬 DB가 필요하다: `docker compose up -d db`.

테스트마다 임시 schema를 쓴다(conftest.py). 실행: `uv run pytest -m db`
"""

import pytest

from specton.contracts import Interrupt, SseEventType
from specton.contracts import RunState as S
from specton.persistence import lease
from specton.persistence.db import Pool, apply_schema, create_checkpointer
from specton.persistence.errors import (
    InvalidTransitionError,
    LeaseLostError,
    RevisionConflictError,
    RunNotFoundError,
)
from specton.persistence.runs import (
    NewEvent,
    create_run,
    events_after,
    get_run,
    list_runs,
    record_progress,
    request_cancel,
)

pytestmark = pytest.mark.db

OWNER = "owner-a"
LEASE = 60
EXPIRED = -1  # 이미 만료된 lease를 만든다
ASK_REQ = Interrupt(interrupt_id="int-req", kind="requirements", message="요구사항 확인")
ASK_EXT = Interrupt(interrupt_id="int-ext", kind="extraction", message="추출 확인")


def _running(pool: Pool, holder: str = "w1") -> str:
    """lease를 잡고 parsing까지 진행한 run."""
    with pool.connection() as conn:
        run = create_run(conn, OWNER, "inventory")
        assert lease.acquire(conn, run.run_id, holder, LEASE)
        record_progress(conn, run.run_id, holder, "cp-1", status=S.PARSING, revision=0)
    return str(run.run_id)


# 표·체크포인터


def test_schema_can_be_applied_twice(pool: Pool) -> None:
    apply_schema(pool)

    with pool.connection() as conn:
        tables = {
            r["table_name"]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            ).fetchall()
        }
    assert tables == {
        "run", "document", "source_block", "model_snapshot", "finding",
        "approval", "artifact", "run_event", "job_lease",
    }  # fmt: skip


def test_schema_adds_new_run_columns_to_an_existing_table(pool: Pool) -> None:
    """#108 스키마로 만든 DB에 다시 적용하면 run의 새 칸이 생긴다 (#110 리뷰)."""
    with pool.connection() as conn:
        run = create_run(conn, OWNER, "inventory")
        conn.execute("ALTER TABLE run DROP COLUMN stage, DROP COLUMN interrupt, DROP COLUMN error")

    apply_schema(pool)

    with pool.connection() as conn:
        assert get_run(conn, run.run_id, OWNER).stage is None


def test_schema_updates_source_block_for_the_extraction_check(pool: Pool) -> None:
    """#95 이전 스키마의 source_block에도 원문 없음 허용과 결정 칸이 생긴다."""
    with pool.connection() as conn:
        conn.execute(
            "ALTER TABLE source_block DROP COLUMN notice, DROP COLUMN user_decision,"
            " DROP COLUMN excluded_reason, ALTER COLUMN source_text SET NOT NULL"
        )

    apply_schema(pool)

    with pool.connection() as conn:
        rows = conn.execute(
            """
            SELECT column_name, is_nullable FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'source_block'
            """
        ).fetchall()
    columns = {r["column_name"]: r["is_nullable"] for r in rows}
    assert {"notice", "user_decision", "excluded_reason"} <= columns.keys()
    assert columns["source_text"] == "YES"


def test_checkpointer_tables_are_created_in_the_same_database(pool: Pool) -> None:
    create_checkpointer(pool)

    with pool.connection() as conn:
        row = conn.execute("SELECT to_regclass('checkpoints') AS t").fetchone()
    assert row is not None and row["t"] is not None


# 소유자 검사 (ADR-0011)


def test_other_owner_cannot_see_the_run(pool: Pool) -> None:
    with pool.connection() as conn:
        run = create_run(conn, OWNER, "inventory")

        assert get_run(conn, run.run_id, OWNER).status is S.QUEUED
        with pytest.raises(RunNotFoundError):
            get_run(conn, run.run_id, "owner-b")
        assert list_runs(conn, "owner-b") == []
        assert [r.run_id for r in list_runs(conn, OWNER)] == [run.run_id]
        with pytest.raises(RunNotFoundError):
            events_after(conn, run.run_id, "owner-b", 0)


# lease


def test_only_one_holder_while_the_lease_is_alive(pool: Pool) -> None:
    with pool.connection() as conn:
        run = create_run(conn, OWNER, "inventory")

        assert lease.acquire(conn, run.run_id, "w1", LEASE)
        assert not lease.acquire(conn, run.run_id, "w2", LEASE)
        assert lease.claimable_runs(conn, 10) == []


def test_expired_lease_can_be_taken_over_and_old_holder_is_rejected(pool: Pool) -> None:
    with pool.connection() as conn:
        run = create_run(conn, OWNER, "inventory")
        assert lease.acquire(conn, run.run_id, "w1", EXPIRED)

        assert lease.claimable_runs(conn, 10) == [run.run_id]
        assert lease.acquire(conn, run.run_id, "w2", LEASE)
        with pytest.raises(LeaseLostError):
            lease.renew(conn, run.run_id, "w1", LEASE)
        with pytest.raises(LeaseLostError):
            record_progress(conn, run.run_id, "w1", "cp-1", status=S.PARSING, revision=0)


def test_released_run_waits_without_a_holder(pool: Pool) -> None:
    run_id = _running(pool)
    with pool.connection() as conn:
        record_progress(conn, run_id, "w1", "cp-2", status=S.ANALYSING, revision=0)
        record_progress(
            conn,
            run_id,
            "w1",
            "cp-3",
            status=S.AWAITING_REQUIREMENTS,
            revision=1,
            interrupt=ASK_REQ,
        )
        lease.release(conn, run_id, "w1")

        assert lease.claimable_runs(conn, 10) == []  # HITL 대기는 실행 대상이 아니다
        assert not lease.acquire(conn, run_id, "w2", LEASE)


# 진행 기록


def test_interrupt_is_given_only_in_waiting_states(pool: Pool) -> None:
    run_id = _running(pool)
    with pool.connection() as conn:
        with pytest.raises(ValueError):
            record_progress(conn, run_id, "w1", "cp-2", status=S.AWAITING_INPUT, revision=0)
        with pytest.raises(ValueError):
            record_progress(
                conn, run_id, "w1", "cp-2", status=S.ANALYSING, revision=0, interrupt=ASK_EXT
            )

        record_progress(
            conn, run_id, "w1", "cp-2", status=S.AWAITING_INPUT, revision=0, interrupt=ASK_EXT
        )

        assert get_run(conn, run_id, OWNER).interrupt == ASK_EXT


def test_progress_writes_status_revision_and_events_together(pool: Pool) -> None:
    run_id = _running(pool)
    with pool.connection() as conn:
        saved = record_progress(
            conn, run_id, "w1", "cp-2", status=S.ANALYSING, revision=1,
            events=[NewEvent(SseEventType.STATUS, "분석 중", stage="analysing")],
        )  # fmt: skip

        assert saved is not None and [e.id for e in saved] == [1]
        assert (get_run(conn, run_id, OWNER).status, get_run(conn, run_id, OWNER).revision) == (
            S.ANALYSING,
            1,
        )
        assert events_after(conn, run_id, OWNER, 0) == saved


def test_saving_the_same_checkpoint_again_changes_nothing(pool: Pool) -> None:
    run_id = _running(pool)
    event = [NewEvent(SseEventType.STATUS, "분석 중")]
    with pool.connection() as conn:
        record_progress(conn, run_id, "w1", "cp-2", status=S.ANALYSING, revision=1, events=event)

        again = record_progress(
            conn, run_id, "w1", "cp-2", status=S.ANALYSING, revision=1, events=event
        )

        assert again is None
        assert len(events_after(conn, run_id, OWNER, 0)) == 1


def test_invalid_transition_is_rolled_back(pool: Pool) -> None:
    run_id = _running(pool)
    with pool.connection() as conn:
        with pytest.raises(InvalidTransitionError):
            record_progress(
                conn, run_id, "w1", "cp-2", status=S.DESIGNING, revision=1,
                events=[NewEvent(SseEventType.STATUS, "설계 중")],
            )  # fmt: skip

        assert get_run(conn, run_id, OWNER).status is S.PARSING
        assert events_after(conn, run_id, OWNER, 0) == []


def test_event_ids_keep_increasing_and_replay_after_an_id(pool: Pool) -> None:
    run_id = _running(pool)
    with pool.connection() as conn:
        record_progress(
            conn, run_id, "w1", "cp-2", status=S.ANALYSING, revision=0,
            events=[NewEvent(SseEventType.STATUS, "a"), NewEvent(SseEventType.STATUS, "b")],
        )  # fmt: skip
        record_progress(
            conn, run_id, "w1", "cp-3", status=S.AWAITING_REQUIREMENTS, revision=0,
            interrupt=ASK_REQ, events=[NewEvent(SseEventType.INTERRUPT, "c")],
        )  # fmt: skip

        assert [e.id for e in events_after(conn, run_id, OWNER, 0)] == [1, 2, 3]
        assert [e.data.message for e in events_after(conn, run_id, OWNER, 2)] == ["c"]


# 취소 (ADR-0012 "취소")


def test_cancel_while_running_waits_for_the_runner(pool: Pool) -> None:
    run_id = _running(pool)
    with pool.connection() as conn:
        state, events = request_cancel(conn, run_id, OWNER, expected_revision=0)

        assert state is S.CANCEL_REQUESTED
        assert [e.event for e in events] == [SseEventType.STATUS]
        # 실행기가 노드 경계에서 끝낸다. 진행 중이던 결과는 올리지 못한다
        with pytest.raises(InvalidTransitionError):
            record_progress(conn, run_id, "w1", "cp-2", status=S.ANALYSING, revision=0)
        record_progress(conn, run_id, "w1", "cp-2", status=S.CANCELLED, revision=0)
        assert get_run(conn, run_id, OWNER).status is S.CANCELLED


@pytest.mark.parametrize("waiting", [False, True])
def test_cancel_without_a_runner_finishes_immediately(pool: Pool, waiting: bool) -> None:
    with pool.connection() as conn:
        if waiting:
            run_id = _running(pool)
            record_progress(
                conn, run_id, "w1", "cp-2", status=S.AWAITING_INPUT, revision=0, interrupt=ASK_EXT
            )
            lease.release(conn, run_id, "w1")
        else:
            run_id = str(create_run(conn, OWNER, "inventory").run_id)

        state, events = request_cancel(conn, run_id, OWNER, expected_revision=0)

        assert state is S.CANCELLED
        assert [e.event for e in events] == [SseEventType.CANCELLED]
        assert lease.claimable_runs(conn, 10) == []


def test_cancel_checks_revision_owner_and_finished_runs(pool: Pool) -> None:
    run_id = _running(pool)
    with pool.connection() as conn:
        with pytest.raises(RevisionConflictError):
            request_cancel(conn, run_id, OWNER, expected_revision=3)
        with pytest.raises(RunNotFoundError):
            request_cancel(conn, run_id, "owner-b", expected_revision=0)

        request_cancel(conn, run_id, OWNER, expected_revision=0)
        assert request_cancel(conn, run_id, OWNER, expected_revision=0) == (
            S.CANCEL_REQUESTED,
            [],
        )
        record_progress(conn, run_id, "w1", "cp-2", status=S.CANCELLED, revision=0)
        with pytest.raises(InvalidTransitionError):
            request_cancel(conn, run_id, OWNER, expected_revision=0)
