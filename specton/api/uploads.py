"""업로드 원문 저장: 확장자·크기 확인, 해시 계산, run별 저장 (06·11 문서).

사용자가 준 파일명은 경로로 쓰지 않는다. 저장 이름은 `document_id`와 형식으로 만든다.

내용 검사 (#21): 확장자만 맞춘 다른 파일과 압축 폭탄을 파서에 넘기기 전에 막는다.
- xlsx·hwpx는 zip이어야 하고, 압축을 푼 크기 합이 한도(`max_unzipped_mb`) 안이어야 한다.
- csv는 텍스트여야 한다(NUL 바이트가 없어야 한다). 인코딩·표 모양은 파서가 판정한다.
"""

import hashlib
import zipfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePath
from uuid import UUID

from fastapi import UploadFile

from specton.api.errors import ApiError
from specton.contracts import ErrorCode

# 이번 범위의 입력 형식 (10/29 결정 2: PDF 제외, R2 합의: HWP는 HWPX로 변환해 올림)
ACCEPTED_FORMATS = ("xlsx", "csv", "hwpx")
_ZIP_FORMATS = frozenset({"xlsx", "hwpx"})
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
    upload: UploadFile,
    storage_dir: Path,
    run_id: UUID,
    document_id: UUID,
    max_bytes: int,
    max_unzipped_bytes: int,
) -> StoredFile:
    """업로드를 저장하고 해시를 계산한다. 한도를 넘으면 지우고 413, 내용이 형식과 다르면 415."""
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
        _discard(target)
        raise
    if size == 0:
        _discard(target)
        raise ApiError(422, ErrorCode.INVALID_REQUEST, "빈 파일입니다.")
    try:
        _check_content(target, file_format, max_unzipped_bytes)
    except BaseException:
        _discard(target)
        raise
    return StoredFile(file_name, file_format, digest.hexdigest(), relative.as_posix())


def _check_content(path: Path, file_format: str, max_unzipped_bytes: int) -> None:
    if file_format in _ZIP_FORMATS:
        if not zipfile.is_zipfile(path):
            raise ApiError(
                415, ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                f"파일 내용이 .{file_format} 형식이 아닙니다. "
                "원래 프로그램에서 다시 저장해 올려 주세요.",
            )  # fmt: skip
        with zipfile.ZipFile(path) as archive:
            unzipped = sum(item.file_size for item in archive.infolist())
        if unzipped > max_unzipped_bytes:
            raise ApiError(
                413, ErrorCode.UPLOAD_TOO_LARGE,
                f"압축을 푼 크기가 {max_unzipped_bytes // (1024 * 1024)}MB를 넘습니다.",
            )  # fmt: skip
    else:
        with path.open("rb") as stream:
            while chunk := stream.read(_CHUNK):
                if b"\x00" in chunk:
                    raise ApiError(
                        415, ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                        "CSV 내용이 텍스트가 아닙니다. 엑셀에서 CSV로 다시 저장해 올려 주세요.",
                    )  # fmt: skip


def discard_upload(storage_dir: Path, stored: StoredFile) -> None:
    """저장한 업로드를 지운다 (run 등록 실패 등)."""
    _discard(storage_dir / stored.storage_ref)


def _discard(target: Path) -> None:
    """파일과, 비었으면 run 폴더까지 지운다."""
    target.unlink(missing_ok=True)
    with suppress(OSError):  # 다른 파일이 남아 있다
        target.parent.rmdir()
