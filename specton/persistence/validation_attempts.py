"""체크포인트의 SQL 검증 시도를 산출물 게시와 같은 트랜잭션에 기록한다 (#17·#167)."""

from collections.abc import Mapping
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from specton.contracts import DesignState
from specton.persistence.validations import save_validation
from specton.validation_attempts import ValidationAttempt, merge_validation_attempts


def publish_validation_attempts(
    conn: Connection[DictRow],
    holder: str,
    state: DesignState,
    attempts: Mapping[str, ValidationAttempt],
) -> None:
    """산출물 게시 뒤, 진행·모델 저장의 외부 트랜잭션 안에서 부른다.

    같은 시각의 최근 시도는 최초 DB 저장 순서로 결정하므로 체크포인트 삽입 순서를 유지한다.
    이미 저장한 과거 시도도 그대로 재전달한다. SQL이 바뀐 뒤 처음 저장하려는 과거 시도는
    저장 함수의 해시 검사에서 거절하며, 현재 시도로 바꾸거나 누락시키지 않는다.
    """
    if not attempts:
        return
    checked = merge_validation_attempts({}, attempts)
    with conn.transaction():
        for attempt in checked.values():
            if attempt["run_id"] != state.run_id:
                raise ValueError("검증 시도가 현재 실행에 속하지 않습니다")
            revision = attempt["artifact"]["ref"].revision
            if revision > state.revision:
                raise ValueError("검증 시도가 현재보다 뒤의 revision에 속합니다")
            save_validation(
                conn,
                UUID(state.run_id),
                holder,
                revision,
                validation_id=UUID(attempt["validation_id"]),
                model_hash=attempt["artifact"]["model_hash"],
                validated_at=attempt["validated_at"],
                result=attempt["result"],
            )
