"""#17·#167: 검증 호출의 ID·산출물 문맥·공용 결과를 체크포인트에 함께 보존한다.

새 검증 호출은 새 ID를 받는다. 저장된 시도를 재전달할 때는 이 함수를 다시 호출하지 않고
체크포인트의 값을 그대로 쓴다. DB 검증 이력 저장과 승인 검사는 인계 후 실행기에서 연결한다.
"""

import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TypedDict
from uuid import UUID, uuid4

from specton.artifacts import GeneratedArtifact, storage_ref
from specton.contracts import DesignState, SqlValidation
from specton.model_hash import model_hash


class ValidationAttempt(TypedDict):
    """검증기에는 넘기지 않는 실행 문맥. 중첩 객체는 기존 체크포인트 허용 계약만 쓴다."""

    validation_id: str
    validated_at: datetime  # 검증 완료 UTC 시각. 재저장 때도 바꾸지 않는다
    run_id: str
    artifact: GeneratedArtifact  # ref의 revision·파일 해시와 생성 당시 model_hash 포함
    result: SqlValidation


def run_validation_attempt(
    design: DesignState,
    artifact: GeneratedArtifact,
    sql_bytes: bytes,
    validate: Callable[[bytes], SqlValidation],
) -> ValidationAttempt:
    """동일 SQL 바이트를 한 번 검증하고 새 시도를 반환한다. 앱 DB에는 쓰지 않는다.

    실행·revision·모델·파일이 다르면 검증 호출 전 거절한다. 정상적인 error 결과도 그대로
    보존하며 예상하지 않은 예외를 가짜 결과로 바꾸지 않는다. 실제 생성 노드는 이 결과와
    generated_artifacts를 함께 반환한다. 현재 API 기본 그래프에는 아직 등록하지 않는다.
    """
    artifact = artifact.copy()
    _check_artifact(design.run_id, artifact)
    if artifact["ref"].revision != design.revision:
        raise ValueError("검증 산출물의 revision이 현재 설계와 다릅니다")
    if artifact["model_hash"] != model_hash(design):
        raise ValueError("검증 산출물의 모델 해시가 현재 설계와 다릅니다")
    if hashlib.sha256(sql_bytes).hexdigest() != artifact["ref"].hash:
        raise ValueError("검증할 SQL 바이트와 산출물 해시가 다릅니다")
    validation_id = str(uuid4())
    result = validate(sql_bytes)
    attempt = ValidationAttempt(
        validation_id=validation_id,
        validated_at=datetime.now(UTC),
        run_id=design.run_id,
        artifact=artifact,
        result=result,
    )
    _check_attempt(validation_id, attempt)
    return attempt


def merge_validation_attempts(
    old: Mapping[str, ValidationAttempt],
    new: Mapping[str, ValidationAttempt],
) -> dict[str, ValidationAttempt]:
    """같은 시도의 재전달은 그대로 두고, 같은 ID의 다른 결과·문맥은 충돌로 거절한다.

    서로 다른 시도는 같은 SQL·버전이어도 모두 보존한다. 검증 시각·최신 순서를 나타내는 값은
    여기서 만들거나 재저장으로 바꾸지 않는다. 새 revision에서도 이전 시도를 덮어쓰지 않는다.
    """
    merged: dict[str, ValidationAttempt] = {}
    run_id: str | None = None
    for group in (old, new):
        for key, attempt in group.items():
            _check_attempt(key, attempt)
            if run_id is not None and attempt["run_id"] != run_id:
                raise ValueError("서로 다른 실행의 검증 시도를 합칠 수 없습니다")
            run_id = attempt["run_id"]
            if key in merged and merged[key] != attempt:
                raise ValueError("같은 검증 시도 ID에 다른 결과나 산출물 문맥이 있습니다")
            merged[key] = ValidationAttempt(
                validation_id=key,
                validated_at=attempt["validated_at"],
                run_id=run_id,
                artifact=attempt["artifact"].copy(),
                result=attempt["result"],
            )
    return merged


def _check_artifact(run_id: str, artifact: GeneratedArtifact) -> None:
    ref = artifact["ref"]
    if (ref.kind, ref.file_format) != ("ddl", "sql"):
        raise ValueError("SQL 검증 시도에는 DDL/SQL 산출물이 필요합니다")
    if artifact["storage_ref"] != storage_ref(run_id, ref):
        raise ValueError("검증 산출물의 저장 참조가 실행·파일 해시와 다릅니다")
    if re.fullmatch(r"[0-9a-f]{64}", artifact["model_hash"]) is None:
        raise ValueError("검증 산출물에는 SHA-256 모델 해시가 필요합니다")


def _check_attempt(key: str, attempt: ValidationAttempt) -> None:
    if key != attempt["validation_id"] or str(UUID(key)) != key:
        raise ValueError("검증 시도 ID와 저장 키는 같은 UUID여야 합니다")
    validated_at = attempt.get("validated_at")
    if not isinstance(validated_at, datetime) or validated_at.utcoffset() is None:
        raise ValueError("검증 시각은 시간대가 있는 datetime이어야 합니다")
    if not isinstance(attempt["result"], SqlValidation):
        raise TypeError("검증기는 공용 SqlValidation 결과를 반환해야 합니다")
    _check_artifact(attempt["run_id"], attempt["artifact"])
    if attempt["result"].artifact_hash != attempt["artifact"]["ref"].hash:
        raise ValueError("검증 결과의 SQL 해시가 산출물 해시와 다릅니다")
