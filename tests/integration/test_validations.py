"""SQL 검증 기록 저장·조회 (#194, #167). 로컬 DB 필요: `docker compose up -d db`."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from specton.contracts import (
    VALIDATION_STEPS,
    ArtifactRef,
    DesignState,
    SqlValidation,
    ValidationIssue,
    ValidationStep,
    overall_status,
)
from specton.model_hash import model_hash
from specton.persistence import lease
from specton.persistence.db import Pool
from specton.persistence.errors import InvalidTransitionError, LeaseLostError
from specton.persistence.runs import add_document, create_run
from specton.persistence.snapshots import add_artifact, save_model
from specton.persistence.validations import latest_validation, save_validation

pytestmark = pytest.mark.db

OWNER = "owner-a"
SQL = b"CREATE TABLE t (id integer PRIMARY KEY);\n"
VERSIONS = {
    "validator_version": "sql-validator-v1",
    "policy_version": "allowed-sql-v1",
    "postgres_version": "postgresql-18",
}
T0 = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
Factory = Callable[[str, str], DesignState]


def _result(sql: bytes = SQL, failed: str | None = None, **versions: str) -> SqlValidation:
    """`failed`로 정한 단계만 실패이고 나머지는 통과인 검증 결과."""
    steps = tuple(
        ValidationStep(name=name, status="failed", issues=(ValidationIssue(code="x"),))
        if name == failed
        else ValidationStep(name=name, status="passed")
        for name in VALIDATION_STEPS
    )
    return SqlValidation(
        status=overall_status(steps),
        artifact_hash=hashlib.sha256(sql).hexdigest(),
        steps=steps,
        **{**VERSIONS, **versions},
    )


def _with_sql(pool: Pool, sample_state: Factory, sql: bytes = SQL) -> tuple[UUID, str]:
    """revision 0 모델과 SQL 산출물을 저장한 run과 그 모델 해시. 실행자 w1이 lease를 잡고 있다."""
    with pool.connection() as conn:
        run = create_run(conn, OWNER, "inventory")
        document_id = uuid4()
        add_document(
            conn, run.run_id, document_id=document_id, file_name="req.xlsx",
            file_format="xlsx", file_hash="h", storage_ref="x",
        )  # fmt: skip
        assert lease.acquire(conn, run.run_id, "w1", 60)
        state = sample_state(str(run.run_id), str(document_id))
        save_model(conn, run.run_id, "w1", state)
        _add_sql(conn, run.run_id, sql)
    return run.run_id, model_hash(state)


def _add_sql(conn, run_id: UUID, sql: bytes) -> None:  # type: ignore[no-untyped-def]
    digest = hashlib.sha256(sql).hexdigest()
    ref = ArtifactRef(kind="ddl", file_format="sql", revision=0, hash=digest)
    add_artifact(conn, run_id, "w1", ref, f"runs/{run_id}/0/{digest}.sql")


def _save(pool: Pool, run_id: UUID, digest: str, result: SqlValidation, **kw: object) -> bool:
    args = {"validation_id": uuid4(), "model_hash": digest, "validated_at": T0, **kw}
    with pool.connection() as conn:
        return save_validation(conn, run_id, "w1", 0, result=result, **args)  # type: ignore[arg-type]


def _latest(pool: Pool, run_id: UUID, **versions: str):  # type: ignore[no-untyped-def]
    with pool.connection() as conn:
        return latest_validation(conn, run_id, 0, **{**VERSIONS, **versions})


def test_saved_attempt_is_the_latest_match(pool: Pool, sample_state: Factory) -> None:
    run_id, digest = _with_sql(pool, sample_state)
    attempt = uuid4()

    assert _save(pool, run_id, digest, _result(), validation_id=attempt)

    stored = _latest(pool, run_id)
    assert stored is not None
    assert (stored.validation_id, stored.model_hash, stored.validated_at) == (attempt, digest, T0)
    assert stored.result == _result()


def test_resaving_the_same_attempt_changes_nothing(pool: Pool, sample_state: Factory) -> None:
    """체크포인트 재저장. 결과가 같으면 그대로 두고, 다르면 거절한다."""
    run_id, digest = _with_sql(pool, sample_state)
    attempt = uuid4()
    _save(pool, run_id, digest, _result(), validation_id=attempt)

    assert not _save(pool, run_id, digest, _result(), validation_id=attempt)
    with pytest.raises(InvalidTransitionError, match="이미 다른 결과"):
        _save(pool, run_id, digest, _result(failed="execute"), validation_id=attempt)
    with pytest.raises(InvalidTransitionError, match="이미 다른 결과"):
        _save(
            pool, run_id, digest, _result(), validation_id=attempt, validated_at=T0 + timedelta(1)
        )


def test_a_newer_attempt_replaces_an_older_pass(pool: Pool, sample_state: Factory) -> None:
    """예전에 통과했어도 새 시도가 실패면 최근 기록은 실패다. 같은 SQL·버전이어도 새 행이다."""
    run_id, digest = _with_sql(pool, sample_state)
    first, second = uuid4(), uuid4()
    _save(pool, run_id, digest, _result(), validation_id=first)
    _save(
        pool, run_id, digest, _result(failed="execute"), validation_id=second,
        validated_at=T0 + timedelta(minutes=5),
    )  # fmt: skip

    # 이전 시도를 다시 저장해도 순서는 바뀌지 않는다
    _save(pool, run_id, digest, _result(), validation_id=first)
    stored = _latest(pool, run_id)

    assert stored is not None
    assert (stored.validation_id, stored.result.status) == (second, "failed")


@pytest.mark.parametrize(
    ("earlier", "later"),
    [
        (UUID(int=2**128 - 1), UUID(int=1)),  # 이전 시도의 ID가 더 큼
        (UUID(int=1), UUID(int=2**128 - 1)),
    ],
)
def test_same_time_attempts_pick_the_later_save(
    pool: Pool, sample_state: Factory, earlier: UUID, later: UUID
) -> None:
    """검증 시각이 같으면 나중에 저장한 시도다. ID 크기로 정하지 않는다 (#196 리뷰)."""
    run_id, digest = _with_sql(pool, sample_state)
    _save(pool, run_id, digest, _result(), validation_id=earlier)
    _save(pool, run_id, digest, _result(failed="execute"), validation_id=later)

    _save(pool, run_id, digest, _result(), validation_id=earlier)  # 재저장은 순서를 바꾸지 않는다
    stored = _latest(pool, run_id)

    assert stored is not None
    assert (stored.validation_id, stored.result.status) == (later, "failed")


def test_records_for_other_versions_are_not_used(pool: Pool, sample_state: Factory) -> None:
    run_id, digest = _with_sql(pool, sample_state)
    _save(pool, run_id, digest, _result(validator_version="sql-validator-v0"))

    assert _latest(pool, run_id) is None
    assert _latest(pool, run_id, validator_version="sql-validator-v0") is not None
    assert (
        _latest(pool, run_id, validator_version="sql-validator-v0", postgres_version="17") is None
    )


def test_records_for_a_previous_sql_are_not_used(pool: Pool, sample_state: Factory) -> None:
    """SQL이 다시 생성되면 이전 SQL의 통과 기록을 쓰지 않는다. 기록은 지우지 않는다."""
    run_id, digest = _with_sql(pool, sample_state)
    _save(pool, run_id, digest, _result())
    new_sql = SQL + b"-- regenerated\n"

    with pool.connection() as conn:
        _add_sql(conn, run_id, new_sql)
        kept = conn.execute("SELECT count(*) AS n FROM artifact_validation").fetchone()

    assert _latest(pool, run_id) is None
    assert kept is not None and kept["n"] == 1
    _save(pool, run_id, digest, _result(new_sql))
    assert _latest(pool, run_id) is not None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"result": _result(SQL + b"x")}, "산출물 해시와 다릅니다"),
        ({"digest": "0" * 64}, "model_hash가 스냅샷과 다릅니다"),
    ],
)
def test_mismatched_hashes_are_rejected(
    pool: Pool, sample_state: Factory, change: dict[str, object], message: str
) -> None:
    run_id, digest = _with_sql(pool, sample_state)
    result = change.get("result", _result())
    with pytest.raises(ValueError, match=message):
        _save(pool, run_id, str(change.get("digest", digest)), result)  # type: ignore[arg-type]
    assert _latest(pool, run_id) is None


def test_sql_artifact_must_be_saved_first(pool: Pool, sample_state: Factory) -> None:
    run_id, digest = _with_sql(pool, sample_state)
    with pool.connection() as conn, pytest.raises(ValueError, match="SQL 산출물을 먼저"):
        save_validation(
            conn, run_id, "w1", 1, validation_id=uuid4(), model_hash=digest,
            validated_at=T0, result=_result(),
        )  # fmt: skip


def test_a_runner_without_the_lease_cannot_save(pool: Pool, sample_state: Factory) -> None:
    run_id, digest = _with_sql(pool, sample_state)
    with pool.connection() as conn, pytest.raises(LeaseLostError):
        save_validation(
            conn, run_id, "w2", 0, validation_id=uuid4(), model_hash=digest,
            validated_at=T0, result=_result(),
        )  # fmt: skip
