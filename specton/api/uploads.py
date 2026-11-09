"""업로드 원문 저장: 확장자·크기 확인, 해시 계산, run별 저장 (06·11 문서).

사용자가 준 파일명은 경로로 쓰지 않는다. 저장 이름은 `document_id`와 형식으로 만든다.

내용 검사 (#21): 확장자만 맞춘 다른 파일과 압축 폭탄을 파서에 넘기기 전에 막는다.
- xlsx·hwpx는 zip이어야 하고, 압축을 푼 크기 합이 한도(`max_unzipped_mb`) 안이어야 한다.
- hwp(HWP 5.0)는 OLE 복합 문서여야 한다(파일 머리 서명). 안의 스트림·암호·배포용 여부는
  파서가 판정한다(#24).
- csv는 텍스트여야 한다(NUL 바이트가 없어야 한다). BOM 있는 UTF-16은 해독되면 통과한다.
  인코딩·표 모양은 파서가 판정한다.
"""

import hashlib
import struct
import zipfile
import zlib
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import BinaryIO
from uuid import UUID

from fastapi import UploadFile

from specton.api.errors import ApiError
from specton.contracts import ErrorCode

# 이번 범위의 입력 형식 (10/29 결정 2: PDF 제외. .hwp는 변환 없이 바로 읽는다, #24)
ACCEPTED_FORMATS = ("xlsx", "csv", "hwpx", "hwp")
_ZIP_FORMATS = frozenset({"xlsx", "hwpx"})
_OLE_SIGNATURE = bytes.fromhex("d0cf11e0a1b11ae1")  # OLE 복합 문서(HWP 5.0) 파일 머리
_LOCAL_HEADER = struct.Struct("<4s5H3L2H")  # zip 로컬 파일 헤더 (30바이트)
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")  # 파서(_decode)가 받는 UTF-16 표시
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
        _check_zip(path, file_format, max_unzipped_bytes)
    elif file_format == "hwp":
        _check_ole(path)
    else:
        _check_text(path)


def _check_ole(path: Path) -> None:
    """HWP 5.0은 OLE 복합 문서다. 확장자만 바꾼 다른 파일을 파서에 넘기지 않는다."""
    with path.open("rb") as stream:
        if stream.read(len(_OLE_SIGNATURE)) != _OLE_SIGNATURE:
            raise ApiError(
                415, ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "파일 내용이 .hwp 형식이 아닙니다. 한글에서 다시 저장해 올려 주세요.",
            )  # fmt: skip


def _check_zip(path: Path, file_format: str, max_unzipped_bytes: int) -> None:
    """zip 항목을 실제로 풀어 보며 크기를 센다. 선언 크기는 믿지 않는다 (#216 리뷰).

    한도를 넘는 순간 멈춰 413, 구조가 깨졌거나 선언 크기·압축 방식이 실제와 다르면 415다.
    """
    try:
        with zipfile.ZipFile(path) as archive, path.open("rb") as raw:
            total = 0
            for info in archive.infolist():
                total += _inflated_size(raw, info, max_unzipped_bytes - total)
                if total > max_unzipped_bytes:
                    raise ApiError(
                        413, ErrorCode.UPLOAD_TOO_LARGE,
                        f"압축을 푼 크기가 {max_unzipped_bytes // (1024 * 1024)}MB를 넘습니다.",
                    )  # fmt: skip
    # zip 구조·인코딩·지원 범위 문제만 입력 오류로 본다. 그 밖의 예외는 코드 오류로 그대로 둔다
    except (
        zipfile.BadZipFile, zlib.error, struct.error, EOFError, OSError,
        UnicodeDecodeError,  # UTF-8 표시를 켠 잘못된 파일명 바이트
        NotImplementedError,  # zipfile이 지원하지 않는 해제 버전
    ) as exc:  # fmt: skip
        raise ApiError(
            415, ErrorCode.UNSUPPORTED_MEDIA_TYPE,
            f"파일 내용이 .{file_format} 형식이 아닙니다. "
            "원래 프로그램에서 다시 저장해 올려 주세요.",
        ) from exc  # fmt: skip


def _inflated_size(raw: BinaryIO, info: zipfile.ZipInfo, budget: int) -> int:
    """항목 하나를 풀어 실제 크기를 돌려준다. `budget`을 넘으면 그 즉시 넘은 값을 돌려준다.

    `ZipExtFile`은 선언 크기에서 결과를 잘라 버리므로 쓰지 않고, 로컬 헤더 뒤의 압축 바이트를
    직접 푼다. 다 풀었는데 선언 크기와 다르면 BadZipFile.
    """
    raw.seek(info.header_offset)
    header = raw.read(_LOCAL_HEADER.size)
    signature, *_, name_length, extra_length = _LOCAL_HEADER.unpack(header)
    if signature != b"PK\x03\x04":
        raise zipfile.BadZipFile("로컬 헤더가 없습니다")
    raw.seek(name_length + extra_length, 1)
    if info.compress_type == zipfile.ZIP_STORED:
        inflate = None
    elif info.compress_type == zipfile.ZIP_DEFLATED:
        inflate = zlib.decompressobj(-zlib.MAX_WBITS)
    else:
        raise zipfile.BadZipFile("xlsx·hwpx가 쓰지 않는 압축 방식입니다")
    size, remaining = 0, info.compress_size
    while remaining > 0:
        chunk = raw.read(min(_CHUNK, remaining))
        if not chunk:
            raise zipfile.BadZipFile("압축 바이트가 잘렸습니다")
        remaining -= len(chunk)
        while chunk:
            if inflate is None:
                size, chunk = size + len(chunk), b""
            else:
                size += len(inflate.decompress(chunk, budget - size + 1))
                chunk = inflate.unconsumed_tail
            if size > budget:
                return size
    if inflate is not None:
        size += len(inflate.flush())
    if size != info.file_size:
        raise zipfile.BadZipFile("선언한 크기와 실제 크기가 다릅니다")
    return size


def _check_text(path: Path) -> None:
    """CSV가 텍스트인지 본다. BOM 있는 UTF-16(엑셀 「유니코드 텍스트」)은 실제로 해독해 본다."""
    not_text = ApiError(
        415, ErrorCode.UNSUPPORTED_MEDIA_TYPE,
        "CSV 내용이 텍스트가 아닙니다. 엑셀에서 CSV로 다시 저장해 올려 주세요.",
    )  # fmt: skip
    with path.open("rb") as stream:
        if stream.read(2) in _UTF16_BOMS:
            try:
                path.read_bytes().decode("utf-16")  # 크기는 업로드 한도 안이다
            except UnicodeDecodeError as exc:
                raise not_text from exc
            return
        stream.seek(0)
        while chunk := stream.read(_CHUNK):
            if b"\x00" in chunk:
                raise not_text


def discard_upload(storage_dir: Path, stored: StoredFile) -> None:
    """저장한 업로드를 지운다 (run 등록 실패 등)."""
    _discard(storage_dir / stored.storage_ref)


def _discard(target: Path) -> None:
    """파일과, 비었으면 run 폴더까지 지운다."""
    target.unlink(missing_ok=True)
    with suppress(OSError):  # 다른 파일이 남아 있다
        target.parent.rmdir()
