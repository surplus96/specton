"""#17 두 연결 동시 실행: 취소와 lease 잡기가 같은 순간에 일어날 때 (PR #108 리뷰, ADR-0012).

lease는 run 행을 FOR SHARE로, 취소는 FOR UPDATE로 잠근다. 먼저 잠근 쪽이 끝날 때까지 다른 쪽이
기다린 뒤 바뀐 상태를 보고 판단해야 한다. 바깥 트랜잭션을 열어 두면 함수 안 트랜잭션은 savepoint가
되어 잠금이 유지된다. 그 사이 다른 연결의 호출이 멈춰 있는지 본 뒤 커밋한다.
"""

import threading
from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest

from specton.contracts import RunState as S
from specton.persistence import lease
from specton.persistence.db import Pool
from specton.persistence.runs import create_run, get_run, request_cancel

pytestmark = pytest.mark.db

OWNER = "owner-a"
LEASE = 60
BLOCKED_FOR = 0.3  # 다른 연결의 호출이 잠금에 막혀 있는지 볼 시간 (초)


class _Call(threading.Thread):
    """다른 연결에서 함수를 부르고 결과를 남긴다."""

    def __init__(self, pool: Pool, call: Callable[[Any], Any]) -> None:
        super().__init__(daemon=True)
        self.pool, self.call = pool, call
        self.result: Any = None

    def run(self) -> None:
        with self.pool.connection() as conn:
            self.result = self.call(conn)


def _queued_run(pool: Pool) -> UUID:
    with pool.connection() as conn:
        return create_run(conn, OWNER, "inventory").run_id


def test_lease_waits_for_a_cancel_in_progress_and_does_not_take_the_cancelled_run(
    pool: Pool,
) -> None:
    run_id = _queued_run(pool)
    take = _Call(pool, lambda conn: lease.acquire(conn, run_id, "w1", LEASE))

    with pool.connection() as conn, conn.transaction():
        request_cancel(conn, run_id, OWNER, expected_revision=0)  # queued → cancelled, 잠금 유지
        take.start()
        take.join(BLOCKED_FOR)
        assert take.is_alive()  # 취소가 커밋되기 전에는 lease를 잡지 못하고 기다린다

    take.join()
    assert take.result is False
    with pool.connection() as conn:
        assert get_run(conn, run_id, OWNER).status is S.CANCELLED


def test_cancel_waits_for_a_lease_in_progress_and_asks_the_runner_to_stop(pool: Pool) -> None:
    run_id = _queued_run(pool)
    cancel = _Call(pool, lambda conn: request_cancel(conn, run_id, OWNER, expected_revision=0))

    with pool.connection() as conn, conn.transaction():
        assert lease.acquire(conn, run_id, "w1", LEASE)  # 잠금 유지
        cancel.start()
        cancel.join(BLOCKED_FOR)
        assert cancel.is_alive()  # lease가 커밋되기 전에는 취소가 기다린다

    cancel.join()
    status, _ = cancel.result
    assert status is S.CANCEL_REQUESTED  # 살아 있는 실행자가 노드 경계에서 끝낸다
