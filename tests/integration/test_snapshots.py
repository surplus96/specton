"""설계 모델·지적·산출물 저장 (05 문서 플랫폼 저장). 로컬 DB 필요: `docker compose up -d db`."""

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest

from specton.contracts import (
    ArtifactRef,
    Column,
    DesignState,
    NormalizedModel,
    SourceRequirement,
    Table,
)
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


def _approve(pool: Pool, run_id: UUID, snapshot_id: UUID) -> None:
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO approval (approval_id, run_id, snapshot_id, interrupt_id, actor_ref,
                decision, response)
            VALUES (%s, %s, %s, 'int-review', %s, 'approve', '{}')
            """,
            (uuid4(), run_id, snapshot_id, OWNER),
        )


def test_approved_model_cannot_change(pool: Pool, sample_state: Factory) -> None:
    run_id, document_id = _running(pool)
    state = sample_state(str(run_id), document_id)
    with pool.connection() as conn:
        snapshot_id = save_model(conn, run_id, "w1", state)
    _approve(pool, run_id, snapshot_id)

    with pool.connection() as conn, pytest.raises(InvalidTransitionError):
        save_model(conn, run_id, "w1", state.evolve(functions=()))


def test_saving_the_approved_model_again_keeps_it(pool: Pool, sample_state: Factory) -> None:
    """승인 뒤 export·complete 노드가 같은 모델을 저장해도 실패하지 않는다 (#113 리뷰)."""
    run_id, document_id = _running(pool)
    state = sample_state(str(run_id), document_id)
    with pool.connection() as conn:
        snapshot_id = save_model(conn, run_id, "w1", state)
    _approve(pool, run_id, snapshot_id)

    with pool.connection() as conn:
        again = save_model(conn, run_id, "w1", state.evolve(findings=()))
        view = get_view(conn, run_id, OWNER, "review")

    assert again == snapshot_id
    assert [f["id"] for f in view.items] == ["A05-1-1"]  # 승인본의 지적은 다시 쓰지 않는다


def _normalized(physical_name: str = "ord") -> NormalizedModel:
    """테이블 1개·컬럼 1개(PK)인 정리 결과."""
    column = Column(
        id="COL-1", name="주문번호", physical_name="ord_no", data_type="varchar", length=20,
        precision=None, scale=None, time_precision=None, domain=None, nullable=False,
        req_ids=("REQ-01",), attribute_id="ATTR-01",
    )  # fmt: skip
    table = Table(
        id="TBL-1", name="주문", physical_name=physical_name, columns=(column,),
        primary_key=("COL-1",), unique_keys=(), req_ids=("REQ-01",), entity_id="ENT-01",
    )  # fmt: skip
    return NormalizedModel(
        pack="inventory", pack_version="0.1.0", rules_version="normalize-v0",
        lexicon_digest="d", tables=(table,), foreign_keys=(),
    )  # fmt: skip


def _stored(pool: Pool, run_id: UUID) -> tuple[dict[str, object], str]:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT normalized_model, model_hash FROM model_snapshot WHERE run_id = %s", (run_id,)
        ).fetchone()
    assert row is not None
    return row["normalized_model"], row["model_hash"]


def test_normalized_model_is_saved_and_hashed_with_the_design(
    pool: Pool, sample_state: Factory
) -> None:
    """정리 결과도 승인본에 묶여 다시 만들 수 있다. 없으면 정리 전과 해시가 같다 (#142)."""
    run_id, document_id = _running(pool)
    state = sample_state(str(run_id), document_id)
    with pool.connection() as conn:
        save_model(conn, run_id, "w1", state)
    before, hash_before = _stored(pool, run_id)

    with pool.connection() as conn:
        snapshot_id = save_model(conn, run_id, "w1", state.evolve(normalized=_normalized()))
    after, hash_after = _stored(pool, run_id)

    assert "normalized" not in before
    assert NormalizedModel.model_validate(after["normalized"]) == _normalized()
    # 새 메타데이터가 없는 옛 모델은 null 키를 추가하지 않아 기존 해시를 유지한다.
    assert "common_version" not in after["normalized"]
    assert "policy_digest" not in after["normalized"]
    assert hash_after != hash_before
    _approve(pool, run_id, snapshot_id)
    with pool.connection() as conn, pytest.raises(InvalidTransitionError):
        save_model(conn, run_id, "w1", state.evolve(normalized=_normalized("order_hdr")))


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


def test_blank_row_and_user_decisions_are_saved_for_the_view(
    pool: Pool, sample_state: Factory
) -> None:
    """원문 없는 행과 추출 확인 결정이 source_block 칸과 화면 조회에 남는다 (#95)."""
    run_id, document_id = _running(pool)
    state = sample_state(str(run_id), document_id)
    excluded = state.source_requirements[0].evolve(
        extraction_status="review", notice="같은 원문 ID", user_decision="excluded",
        excluded_reason="2차 범위",
    )  # fmt: skip
    blank = SourceRequirement(
        document_id=document_id, block_id="B-2", source_ref={"file_format": "xlsx",
        "sheet": "요구사항", "row": 6}, source_text=None, extraction_status="review",
        notice="내용 칸이 비어 있습니다", user_decision="confirmed",
    )  # fmt: skip

    with pool.connection() as conn:
        save_model(conn, run_id, "w1", state.evolve(source_requirements=(excluded, blank)))
        rows = conn.execute(
            "SELECT block_id, source_text, notice, user_decision, excluded_reason"
            " FROM source_block ORDER BY block_id"
        ).fetchall()
        view = get_view(conn, run_id, OWNER, "extraction")

    assert [tuple(r.values()) for r in rows] == [
        ("B-1", "주문을 취소할 수 있다", "같은 원문 ID", "excluded", "2차 범위"),
        ("B-2", None, "내용 칸이 비어 있습니다", "confirmed", None),
    ]
    assert [b["user_decision"] for b in view.items] == ["excluded", "confirmed"]
