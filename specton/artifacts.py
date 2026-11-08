"""생성 노드의 공통 파일 저장과 체크포인트용 인계 정보. DB에는 실행기가 기록한다.

파일을 먼저 불변 경로에 쓰고, 메타데이터를 그래프에 반환한다. DB 게시 전 중단된 파일은
다운로드에 노출되지 않는다. 실제 생성기 어댑터는 이 함수를 사용해 결과를 반환한다.
"""

import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal, TypedDict
from uuid import UUID

from specton.contracts import ArtifactRef, DesignState
from specton.model_hash import model_hash

ArtifactKind = Literal["requirements", "functions", "erd", "ddl", "rtm", "review"]
FileFormat = Literal["md", "pdf", "mmd", "sql", "xlsx", "csv"]
ARTIFACT_FORMATS: dict[str, tuple[str, ...]] = {
    "requirements": ("md",),
    "functions": ("md", "pdf"),
    "erd": ("mmd", "pdf"),
    "ddl": ("sql",),
    "rtm": ("xlsx", "csv"),
    "review": ("md",),
}


class GeneratedArtifact(TypedDict):
    ref: ArtifactRef
    storage_ref: str
    model_hash: str


def artifact_key(ref: ArtifactRef) -> str:
    return f"{ref.revision}:{ref.kind}:{ref.file_format}"


def storage_ref(run_id: str, ref: ArtifactRef) -> str:
    # UUID와 파일 해시 이외의 외부 문자열을 경로에 넣지 않는다.
    if len(ref.hash) != 64 or any(c not in "0123456789abcdef" for c in ref.hash):
        raise ValueError("산출물에는 SHA-256 파일 해시가 필요합니다")
    return f"{UUID(run_id)}/r{ref.revision}/{ref.kind}-{ref.hash}.{ref.file_format}"


def artifact_path(root: Path, run_id: str, ref: ArtifactRef) -> Path:
    root = root.resolve()
    path = root / storage_ref(run_id, ref)
    if not path.resolve().is_relative_to(root):
        raise ValueError("산출물 경로가 저장소를 벗어납니다")
    return path


def write_artifact(
    root: Path,
    state: DesignState,
    kind: ArtifactKind,
    file_format: FileFormat,
    content: bytes,
    *,
    approved: bool = False,
) -> GeneratedArtifact:
    """완성된 바이트를 저장한다. 승인 여부는 실행기가 DB 승인 기록으로 다시 확인한다."""
    if file_format not in ARTIFACT_FORMATS[kind]:
        raise ValueError(f"허용하지 않는 산출물 형식: {kind}.{file_format}")
    ref = ArtifactRef(
        kind=kind, file_format=file_format, revision=state.revision,
        hash=hashlib.sha256(content).hexdigest(), approved=approved,
    )  # fmt: skip
    path = artifact_path(root, state.run_id, ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 완성 전 파일을 공개 경로에 두지 않고, 기존 파일은 덮어쓰지 않는다.
    with NamedTemporaryFile(dir=path.parent) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        try:
            os.link(temporary.name, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError("기존 산출물 파일이 해시와 다릅니다") from None
    return {
        "ref": ref,
        "storage_ref": storage_ref(state.run_id, ref),
        "model_hash": model_hash(state),
    }
