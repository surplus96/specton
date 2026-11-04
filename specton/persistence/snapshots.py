"""설계 모델·지적·산출물 저장과 화면용 조회 (05 문서 "플랫폼 저장", 06 문서 `view`·`artifacts`).

실행기(#17)가 노드 뒤 `record_progress`와 같은 트랜잭션에서 `save_model`·`add_artifact`를 부르고,
API는 이 표만 읽는다. 체크포인트는 읽지 않는다 (ADR-0012 "화면 상태는 run 기준", #110 리뷰 답 2).

`model_snapshot.normalized_model`은 `DesignState`의 `requirements`·`functions`·`entities`·
`relationships`를 같은 이름의 칸으로 담는다. 같은 revision은 승인 전까지 덮어쓸 수 있고,
승인 뒤에는 같은 모델을 다시 저장하는 것만 허용한다 (승인 뒤 export·complete 노드도 저장한다).
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from specton.contracts import ArtifactRef, DesignState, RunView
from specton.contracts.base import Contract
from specton.persistence.errors import (
    ArtifactNotReadyError,
    InvalidTransitionError,
    RevisionConflictError,
    RunNotFoundError,
)
from specton.persistence.lease import check_holder

Section = Literal["extraction", "requirements", "design", "review"]
ArtifactKind = Literal["requirements", "functions", "erd", "ddl", "rtm", "review"]
FileFormat = Literal["md", "pdf", "mmd", "sql", "xlsx", "csv"]

MODEL_FIELDS = ("requirements", "functions", "entities", "relationships")
# 설계 화면 항목의 종류. 한 목록에 섞어 보내므로 `type`으로 구분한다
_DESIGN_TYPES = {"functions": "function", "entities": "entity", "relationships": "relationship"}


@dataclass(frozen=True)
class StoredArtifact:
    ref: ArtifactRef
    storage_ref: str  # storage_dir 기준 상대 위치. 응답에 넣지 않는다


def save_model(conn: Connection[DictRow], run_id: UUID, holder: str, state: DesignState) -> UUID:
    """노드가 끝난 뒤 추출 원문·모델·지적을 저장한다. lease를 가진 실행자만 쓸 수 있다.

    같은 상태를 다시 저장해도 결과가 같다(멱등). 승인된 revision은 모델이 같으면 아무것도
    다시 쓰지 않고, 다르면 InvalidTransitionError다. 돌려주는 값은 그 revision의 `snapshot_id`다.
    """
    model = {
        name: [m.model_dump(mode="json") for m in getattr(state, name)] for name in MODEL_FIELDS
    }
    model_hash = hashlib.sha256(
        json.dumps(model, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    with conn.transaction():
        _lock_for_writer(conn, run_id, holder)
        # 승인도 run 행을 잠그고 기록하므로 잠금 뒤에 확인하면 그 사이에 바뀌지 않는다
        approved = conn.execute(
            """
            SELECT s.snapshot_id, s.model_hash FROM model_snapshot s
            WHERE s.run_id = %s AND s.revision = %s AND EXISTS (
                SELECT 1 FROM approval a
                WHERE a.snapshot_id = s.snapshot_id AND a.decision = 'approve')
            """,
            (run_id, state.revision),
        ).fetchone()
        if approved is not None:
            if approved["model_hash"] != model_hash:
                raise InvalidTransitionError(
                    f"revision {state.revision}은 승인되어 바꿀 수 없습니다"
                )
            approved_id: UUID = approved["snapshot_id"]
            return approved_id  # 승인본의 원문·지적도 그대로 둔다
        for block in state.source_requirements:
            conn.execute(
                """
                INSERT INTO source_block (document_id, block_id, source_ref, source_text,
                    extraction_status, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id, block_id) DO UPDATE SET
                    source_ref = EXCLUDED.source_ref, source_text = EXCLUDED.source_text,
                    extraction_status = EXCLUDED.extraction_status, payload = EXCLUDED.payload
                """,
                (
                    block.document_id, block.block_id, _jsonb(block.source_ref),
                    block.source_text, block.extraction_status, _jsonb(block),
                ),
            )  # fmt: skip
        row = conn.execute(
            """
            INSERT INTO model_snapshot (snapshot_id, run_id, revision, normalized_model, model_hash)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (run_id, revision) DO UPDATE SET
                normalized_model = EXCLUDED.normalized_model, model_hash = EXCLUDED.model_hash
            RETURNING snapshot_id
            """,
            (uuid4(), run_id, state.revision, Jsonb(model), model_hash),
        ).fetchone()
        assert row is not None  # INSERT … DO UPDATE는 항상 한 행을 돌려준다
        snapshot_id: UUID = row["snapshot_id"]
        # 지적은 이번 iteration에서 새로 모은 것으로 바꾼다 (03 문서 상태·버전)
        conn.execute("DELETE FROM finding WHERE snapshot_id = %s", (snapshot_id,))
        for finding in state.findings:
            conn.execute(
                """
                INSERT INTO finding (snapshot_id, finding_id, source, reviewer_or_rule,
                    fingerprint, iteration, payload)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    snapshot_id, finding.id, finding.source,
                    finding.reviewer_id or finding.rule_code, finding.fingerprint,
                    finding.iteration, _jsonb(finding),
                ),
            )  # fmt: skip
    return snapshot_id


def add_artifact(
    conn: Connection[DictRow], run_id: UUID, holder: str, ref: ArtifactRef, storage_ref: str
) -> None:
    """생성한 산출물 파일을 기록한다. 그 revision의 모델이 먼저 저장되어 있어야 한다."""
    with conn.transaction():
        _lock_for_writer(conn, run_id, holder)
        row = conn.execute(
            """
            INSERT INTO artifact (artifact_id, snapshot_id, kind, file_format, hash,
                storage_ref, approval_status)
            SELECT %s, snapshot_id, %s, %s, %s, %s, %s FROM model_snapshot
            WHERE run_id = %s AND revision = %s
            ON CONFLICT (snapshot_id, kind, file_format) DO UPDATE SET
                hash = EXCLUDED.hash, storage_ref = EXCLUDED.storage_ref,
                approval_status = EXCLUDED.approval_status
            RETURNING artifact_id
            """,
            (
                uuid4(), ref.kind, ref.file_format, ref.hash, storage_ref,
                "approved" if ref.approved else "draft", run_id, ref.revision,
            ),
        ).fetchone()  # fmt: skip
        if row is None:
            raise ValueError(f"revision {ref.revision}의 모델을 먼저 저장해야 합니다 (save_model)")


def get_view(
    conn: Connection[DictRow],
    run_id: UUID,
    owner_ref: str,
    section: Section,
    revision: int | None = None,
) -> RunView:
    """화면용 조회. `revision`을 생략하면 현재 revision. 현재보다 크면 RevisionConflictError.

    아직 그 단계 결과가 없으면 빈 목록이다. 추출 원문은 revision과 상관없이 run의 문서 전체다.
    """
    current = _run_revision(conn, run_id, owner_ref)
    revision = current if revision is None else revision
    if revision > current:
        raise RevisionConflictError(str(run_id), current)
    items: list[dict[str, Any]]
    if section == "extraction":
        rows = conn.execute(
            """
            SELECT b.payload FROM source_block b JOIN document d USING (document_id)
            WHERE d.run_id = %s ORDER BY d.created_at, b.block_id
            """,
            (run_id,),
        ).fetchall()
        items = [r["payload"] for r in rows]
    elif section == "review":
        rows = conn.execute(
            """
            SELECT f.payload FROM finding f JOIN model_snapshot s USING (snapshot_id)
            WHERE s.run_id = %s AND s.revision = %s ORDER BY f.finding_id
            """,
            (run_id, revision),
        ).fetchall()
        items = [r["payload"] for r in rows]
    else:
        model = _model(conn, run_id, revision)
        if section == "requirements":
            items = list(model.get("requirements", []))
        else:
            items = [
                {"type": kind, **item}
                for name, kind in _DESIGN_TYPES.items()
                for item in model.get(name, [])
            ]
    artifacts = [a.ref.model_dump(mode="json") for a in _artifacts(conn, run_id, revision)]
    return RunView(
        run_id=run_id, revision=revision, section=section, items=tuple(items),
        artifacts=tuple(artifacts),
    )  # fmt: skip


def find_artifact(
    conn: Connection[DictRow],
    run_id: UUID,
    owner_ref: str,
    kind: ArtifactKind,
    file_format: FileFormat,
    revision: int,
) -> StoredArtifact:
    """내려받을 산출물. 없거나 PDF인데 승인본이 아니면 ArtifactNotReadyError (06 문서)."""
    _run_revision(conn, run_id, owner_ref)
    for stored in _artifacts(conn, run_id, revision):
        if stored.ref.kind == kind and stored.ref.file_format == file_format:
            if file_format == "pdf" and not stored.ref.approved:
                break
            return stored
    raise ArtifactNotReadyError(f"{kind}.{file_format} revision {revision}")


def _jsonb(model: Contract) -> Jsonb:
    return Jsonb(model.model_dump(mode="json"))


def _lock_for_writer(conn: Connection[DictRow], run_id: UUID, holder: str) -> None:
    """run → job_lease 순서로 잠근다 (lease.py 잠금 순서). lease를 잃었으면 LeaseLostError."""
    if conn.execute("SELECT 1 FROM run WHERE run_id = %s FOR UPDATE", (run_id,)).fetchone() is None:
        raise RunNotFoundError(str(run_id))
    check_holder(conn, run_id, holder)


def _run_revision(conn: Connection[DictRow], run_id: UUID, owner_ref: str) -> int:
    row = conn.execute(
        "SELECT revision FROM run WHERE run_id = %s AND owner_ref = %s", (run_id, owner_ref)
    ).fetchone()
    if row is None:
        raise RunNotFoundError(str(run_id))
    revision: int = row["revision"]
    return revision


def _model(conn: Connection[DictRow], run_id: UUID, revision: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT normalized_model FROM model_snapshot WHERE run_id = %s AND revision = %s",
        (run_id, revision),
    ).fetchone()
    return {} if row is None else dict(row["normalized_model"])


def _artifacts(conn: Connection[DictRow], run_id: UUID, revision: int) -> list[StoredArtifact]:
    rows = conn.execute(
        """
        SELECT a.kind, a.file_format, a.hash, a.storage_ref, a.approval_status
        FROM artifact a JOIN model_snapshot s USING (snapshot_id)
        WHERE s.run_id = %s AND s.revision = %s ORDER BY a.kind, a.file_format
        """,
        (run_id, revision),
    ).fetchall()
    return [
        StoredArtifact(
            ArtifactRef(
                kind=r["kind"], file_format=r["file_format"], revision=revision, hash=r["hash"],
                approved=r["approval_status"] == "approved",
            ),
            r["storage_ref"],
        )
        for r in rows
    ]  # fmt: skip
