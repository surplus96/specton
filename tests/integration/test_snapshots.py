"""설계 모델·지적·산출물 저장 (05 문서 플랫폼 저장). 로컬 DB 필요: `docker compose up -d db`."""

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from specton.contracts import ArtifactRef, DesignState
from specton.persistence import lease
from specton.persistence.db import Pool
from specton.persistence.errors import InvalidTransitionError, LeaseLostError
from specton.persistence.runs import add_document, create_run
from specton.persistence.snapshots import add_artifact, get_view, save_model

pytestmark = pytest.mark.db

OWNER = "owner-a"
Factory = Callable[[str, str], DesignState]


def _running(pool: Pool) -> tuple[UUID, str]:
    """문서 1건을 가진 run과 그 문서 ID. 실행자 w1이 lease를 잡고 있다."""
    with pool.connection() as conn:
        run = create_run(conn, OWNER, "inventory")
        document_id = uuid4()
        add_document(
            conn, run.run_id, document_id=document_id, file_name="req.xlsx",
            file_format="xlsx", file_hash="h", storage_ref="x",
        )  # fmt: skip
        assert lease.acquire(conn, run.run_id, "w1", 60)
    return run.run_id, str(document_id)


def test_saving_the_same_state_again_keeps_one_snapshot(pool: Pool, sample_state: Factory) -> None:
    run_id, document_id = _running(pool)
    state = sample_state(str(run_id), document_id)

    with pool.connection() as conn:
        first = save_model(conn, run_id, "w1", state)
        second = save_model(conn, run_id, "w1", state.evolve(findings=()))
        view = get_view(conn, run_id, OWNER, "review")

    assert first == second
    assert view.items == ()  # 지적은 마지막 저장으로 바뀐다


def test_approved_model_cannot_change(pool: Pool, sample_state: Factory) -> None:
    run_id, document_id = _running(pool)
    state = sample_state(str(run_id), document_id)
    with pool.connection() as conn:
        snapshot_id = save_model(conn, run_id, "w1", state)
        conn.execute(
            """
            INSERT INTO approval (approval_id, run_id, snapshot_id, interrupt_id, actor_ref,
                decision, response)
            VALUES (%s, %s, %s, 'int-review', %s, 'approve', '{}')
            """,
            (uuid4(), run_id, snapshot_id, OWNER),
        )

        with pytest.raises(InvalidTransitionError):
            save_model(conn, run_id, "w1", state.evolve(functions=()))


def test_only_the_lease_holder_can_write(pool: Pool, sample_state: Factory) -> None:
    run_id, document_id = _running(pool)
    state = sample_state(str(run_id), document_id)
    ref = ArtifactRef(kind="ddl", file_format="sql", revision=0, hash="h")

    with pool.connection() as conn:
        with pytest.raises(LeaseLostError):
            save_model(conn, run_id, "w2", state)
        with pytest.raises(LeaseLostError):
            add_artifact(conn, run_id, "w2", ref, "x.sql")


def test_artifact_needs_the_model_of_its_revision(pool: Pool) -> None:
    run_id, _ = _running(pool)
    ref = ArtifactRef(kind="ddl", file_format="sql", revision=0, hash="h")

    with pool.connection() as conn, pytest.raises(ValueError, match="save_model"):
        add_artifact(conn, run_id, "w1", ref, "x.sql")
