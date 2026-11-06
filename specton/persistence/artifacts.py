"""체크포인트의 생성 결과를 앱 조회·다운로드와 이벤트에 함께 게시한다."""

import hashlib
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from specton.artifacts import (
    ARTIFACT_FORMATS,
    GeneratedArtifact,
    artifact_key,
    artifact_path,
    storage_ref,
)
from specton.contracts import DesignState, SseEventType
from specton.model_hash import model_hash
from specton.persistence import runs, snapshots
from specton.persistence.errors import InvalidTransitionError
from specton.persistence.runs import NewEvent


def publish_artifacts(
    conn: Connection[DictRow],
    holder: str,
    state: DesignState,
    generated: Mapping[str, GeneratedArtifact],
    root: Path,
) -> None:
    """진행·모델 저장의 외부 트랜잭션 안에서 부른다. 같은 파일은 이벤트도 다시 쓰지 않는다."""
    if not generated:
        return
    run_id = UUID(state.run_id)
    digest = model_hash(state)
    events: list[NewEvent] = []
    with conn.transaction():
        for key, item in sorted(generated.items()):
            ref = item["ref"]
            if ref.revision < state.revision:
                continue  # 과거 revision은 해당 스냅샷에 그대로 둔다
            if ref.revision != state.revision or key != artifact_key(ref):
                raise ValueError("생성 결과의 revision 또는 식별자가 맞지 않습니다")
            if item["model_hash"] != digest:
                raise ValueError("산출물이 현재 모델에서 생성되지 않았습니다")
            if ref.file_format not in ARTIFACT_FORMATS[ref.kind]:
                raise ValueError("허용하지 않는 산출물 형식입니다")
            if item["storage_ref"] != storage_ref(state.run_id, ref):
                raise ValueError("산출물 경로가 실행·revision·파일 해시와 다릅니다")
            path = artifact_path(root, state.run_id, ref)
            with path.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != ref.hash:
                    raise ValueError("산출물 파일이 해시와 다릅니다")
            if ref.approved:
                approved = conn.execute(
                    "SELECT 1 FROM approval a JOIN model_snapshot s USING (snapshot_id) "
                    "WHERE a.run_id = %s AND s.revision = %s AND a.decision = 'approve'",
                    (run_id, ref.revision),
                ).fetchone()
                if approved is None:
                    raise InvalidTransitionError("승인 기록 없이 승인본을 게시할 수 없습니다")
            changed = snapshots.add_artifact(conn, run_id, holder, ref, item["storage_ref"])
            if changed:
                events.append(NewEvent(
                    SseEventType.ARTIFACT, "산출물을 저장했습니다", stage=state.status.value,
                    payload=ref.model_dump(mode="json"),
                ))  # fmt: skip
        if events:
            runs.record_events(conn, run_id, holder, state.revision, events)
