"""SQL 검증 기록 저장·조회 (#167, #194, 05 문서 "플랫폼 저장 모델").

실행기(#17)가 검증 시도 ID를 붙여 `save_validation`을 부른다. 노드는 앱 DB에 쓰지 않는다.
승인 검사는 `latest_validation`으로 지금 SQL에 맞는 가장 최근 시도를 읽는다.

- 시도마다 한 행이고 지우지 않는다. 같은 SQL·버전이어도 새로 검증하면 새 행이다.
- 같은 시도의 체크포인트 재저장(같은 ID)은 결과가 같으면 아무것도 바꾸지 않고, 다르면 거절한다.
  재저장으로 검증 시각이나 최근 순서를 바꾸지 않는다.
- 가장 최근 시도는 검증 시각으로 고르고, 시각이 같으면 먼저 저장된 순서(`saved_order`)로 나중 것을
  고른다. 시도 ID(UUID)의 크기로 정하지 않는다 (#196 리뷰).
- SQL이 다시 생성되면 artifact 행의 해시가 바뀌므로, 이전 시도는 해시가 달라 조회되지 않는다.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from specton.contracts import SqlValidation
from specton.persistence.errors import InvalidTransitionError
from specton.persistence.snapshots import lock_for_writer

# 검증 대상 산출물. DDL 생성기(#165)가 내는 SQL 파일 하나다
_KIND, _FORMAT = "ddl", "sql"
_COLUMNS = (
    "artifact_id", "artifact_hash", "model_hash", "status", "steps",
    "validator_version", "policy_version", "postgres_version", "validated_at",
)  # fmt: skip


@dataclass(frozen=True)
class StoredValidation:
    validation_id: UUID
    model_hash: str
    validated_at: datetime
    result: SqlValidation


def save_validation(
    conn: Connection[DictRow],
    run_id: UUID,
    holder: str,
    revision: int,
    *,
    validation_id: UUID,
    model_hash: str,
    validated_at: datetime,
    result: SqlValidation,
) -> bool:
    """검증 시도 하나를 기록하고 새로 썼는지 돌려준다. lease를 가진 실행자만 쓸 수 있다.

    그 revision의 SQL 산출물(`add_artifact`)이 먼저 있어야 한다. 검증한 해시가 산출물 해시와
    다르거나 `model_hash`가 스냅샷과 다르면 ValueError, 같은 ID에 다른 결과가 오면
    InvalidTransitionError.
    """
    with conn.transaction():
        lock_for_writer(conn, run_id, holder)
        artifact = conn.execute(
            "SELECT a.artifact_id, a.hash, s.model_hash FROM artifact a "
            "JOIN model_snapshot s USING (snapshot_id) "
            "WHERE s.run_id = %s AND s.revision = %s AND a.kind = %s AND a.file_format = %s",
            (run_id, revision, _KIND, _FORMAT),
        ).fetchone()
        if artifact is None:
            raise ValueError(
                f"revision {revision}의 SQL 산출물을 먼저 저장해야 합니다 (add_artifact)"
            )
        if result.artifact_hash != artifact["hash"]:
            raise ValueError("검증한 SQL 해시가 저장된 산출물 해시와 다릅니다")
        if model_hash != artifact["model_hash"]:
            raise ValueError("검증 기록의 model_hash가 스냅샷과 다릅니다")
        row = _row(artifact["artifact_id"], model_hash, validated_at, result)
        inserted = conn.execute(
            f"INSERT INTO artifact_validation (validation_id, {', '.join(_COLUMNS)}) "
            f"VALUES (%s, {', '.join(['%s'] * len(_COLUMNS))}) "
            "ON CONFLICT (validation_id) DO NOTHING RETURNING validation_id",
            (validation_id, *(row[c] for c in _COLUMNS)),
        ).fetchone()
        if inserted is not None:
            return True
        existing = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM artifact_validation WHERE validation_id = %s",
            (validation_id,),
        ).fetchone()
        if existing is None or _differs(existing, row):
            raise InvalidTransitionError(f"검증 시도 {validation_id}에 이미 다른 결과가 있습니다")
        return False


def latest_validation(
    conn: Connection[DictRow],
    run_id: UUID,
    revision: int,
    *,
    validator_version: str,
    policy_version: str,
    postgres_version: str,
) -> StoredValidation | None:
    """그 revision의 지금 SQL 해시·스냅샷 `model_hash`·세 버전이 맞는 가장 최근 시도.

    없으면 None이다. 다른 버전의 기록이나 이전 SQL의 기록으로 대신하지 않는다 (#167 기준 4).
    """
    row = conn.execute(
        """
        SELECT v.validation_id, v.model_hash, v.validated_at, v.status, v.artifact_hash,
            v.validator_version, v.policy_version, v.postgres_version, v.steps
        FROM artifact_validation v
        JOIN artifact a USING (artifact_id)
        JOIN model_snapshot s USING (snapshot_id)
        WHERE s.run_id = %s AND s.revision = %s AND a.kind = %s AND a.file_format = %s
            AND v.artifact_hash = a.hash AND v.model_hash = s.model_hash
            AND v.validator_version = %s AND v.policy_version = %s AND v.postgres_version = %s
        ORDER BY v.validated_at DESC, v.saved_order DESC
        LIMIT 1
        """,
        (run_id, revision, _KIND, _FORMAT, validator_version, policy_version, postgres_version),
    ).fetchone()
    if row is None:
        return None
    result = SqlValidation.model_validate({
        k: row[k] for k in (
            "status", "artifact_hash", "validator_version", "policy_version",
            "postgres_version", "steps",
        )
    })  # fmt: skip
    return StoredValidation(row["validation_id"], row["model_hash"], row["validated_at"], result)


def _row(
    artifact_id: UUID, model_hash: str, validated_at: datetime, result: SqlValidation
) -> dict[str, Any]:
    data = result.model_dump(mode="json")
    return {
        "artifact_id": artifact_id,
        "artifact_hash": result.artifact_hash,
        "model_hash": model_hash,
        "status": data["status"],
        "steps": Jsonb(data["steps"]),
        "validator_version": result.validator_version,
        "policy_version": result.policy_version,
        "postgres_version": result.postgres_version,
        "validated_at": validated_at,
    }


def _differs(existing: DictRow, new: dict[str, Any]) -> bool:
    return any(
        existing[c] != (new[c].obj if isinstance(new[c], Jsonb) else new[c]) for c in _COLUMNS
    )
