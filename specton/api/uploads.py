"""업로드 원문 저장: 확장자·크기 확인, 해시 계산, run별 저장 (06·11 문서).

사용자가 준 파일명은 경로로 쓰지 않는다. 저장 이름은 `document_id`와 형식으로 만든다.
MIME 내용 검사·페이지 한도는 #21에서 더한다.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePath
from uuid import UUID

from fastapi import UploadFile

from specton.api.errors import ApiError
from specton.contracts import ErrorCode

# 이번 범위의 입력 형식 (10/29 결정 2: PDF 제외, R2 합의: HWP는 HWPX로 변환해 올림)
ACCEPTED_FORMATS = ("xlsx", "csv", "hwpx")
_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class StoredFile:
    file_name: str
    file_format: str
    file_hash: str
    storage_ref: str  # storage_dir 기준 상대 위치


def file_format_of(file_name: str) -> str:
    """확장자로 입력 형식을 정한다. 받지 않는 형식이면 415."""
    suffix = PurePath(file_name).suffix.lower().lstrip(".")
    if suffix == "hwp":
        raise ApiError(
            415,
            ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            "HWP는 지원하지 않습니다. 한글에서 HWPX로 저장해 다시 올려 주세요.",
        )
    if suffix not in ACCEPTED_FORMATS:
        allowed = ", ".join(f".{f}" for f in ACCEPTED_FORMATS)
        raise ApiError(415, ErrorCode.UNSUPPORTED_MEDIA_TYPE, f"지원하는 형식은 {allowed}입니다.")
    return suffix


def save_upload(
    upload: UploadFile, storage_dir: Path, run_id: UUID, document_id: UUID, max_bytes: int
) -> StoredFile:
    """업로드를 저장하고 해시를 계산한다. 한도를 넘으면 지우고 413."""
    file_name = PurePath(upload.filename or "").name
    file_format = file_format_of(file_name)
    relative = Path(str(run_id)) / f"{document_id}.{file_format}"
    target = storage_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    try:
        with target.open("xb") as out:
            while chunk := upload.file.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise ApiError(
                        413,
                        ErrorCode.UPLOAD_TOO_LARGE,
                        f"파일이 {max_bytes // (1024 * 1024)}MB를 넘습니다.",
                    )
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if size == 0:
        target.unlink(missing_ok=True)
        raise ApiError(422, ErrorCode.INVALID_REQUEST, "빈 파일입니다.")
    return StoredFile(file_name, file_format, digest.hexdigest(), relative.as_posix())
