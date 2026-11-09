"""업로드 저장 (06·11 문서). 실패하면 파일과 빈 run 폴더를 남기지 않는다."""

import struct
import zipfile
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import UploadFile

from specton.api.errors import ApiError
from specton.api.uploads import save_upload


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(BytesIO(data), filename=name)


def test_saves_under_run_folder_with_hash(tmp_path: Path) -> None:
    run_id, document_id = uuid4(), uuid4()

    stored = save_upload(_upload("../req.csv", b"a,b\n"), tmp_path, run_id, document_id, 1024, 1024)

    assert stored.file_name == "req.csv"
    assert stored.storage_ref == f"{run_id}/{document_id}.csv"
    assert (tmp_path / stored.storage_ref).read_bytes() == b"a,b\n"


@pytest.mark.parametrize(("data", "status"), [(b"a" * 2048, 413), (b"", 422)])
def test_failed_upload_leaves_nothing(tmp_path: Path, data: bytes, status: int) -> None:
    with pytest.raises(ApiError) as caught:
        save_upload(_upload("req.csv", data), tmp_path, uuid4(), uuid4(), 1024, 1024)

    assert caught.value.status == status
    assert not any(tmp_path.iterdir())


MIB = 1024 * 1024


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _spoofed(data: bytes, declared: int) -> bytes:
    """첫 항목의 로컬·중앙 헤더에 적힌 해제 크기를 `declared`로 바꾼 zip (크기 위조)."""
    patched = bytearray(data)
    struct.pack_into("<L", patched, 22, declared)  # 로컬 헤더 해제 크기
    central = patched.index(b"PK\x01\x02")
    struct.pack_into("<L", patched, central + 24, declared)  # 중앙 디렉터리 해제 크기
    return bytes(patched)


def _save(name: str, data: bytes, tmp_path: Path, unzipped: int = 200 * MIB):  # type: ignore[no-untyped-def]
    return save_upload(_upload(name, data), tmp_path, uuid4(), uuid4(), 20 * MIB, unzipped)


def _rejected(name: str, data: bytes, tmp_path: Path, unzipped: int = 200 * MIB) -> ApiError:
    with pytest.raises(ApiError) as caught:
        _save(name, data, tmp_path, unzipped)
    assert not any(p.is_file() for p in tmp_path.rglob("*"))  # 파서에 넘기지 않고 지운다
    return caught.value


def test_utf16_csv_with_bom_is_accepted(tmp_path: Path) -> None:
    """엑셀 「유니코드 텍스트」 저장(UTF-16 BOM)은 파서가 읽는 형식이다 (#216 리뷰)."""
    data = "요구사항 ID\t요구사항명\nINV-001\t입고\n".encode("utf-16")

    assert _save("req.csv", data, tmp_path).file_format == "csv"


@pytest.mark.parametrize(
    "data",
    [
        b"id,text\n1,\x00\x01",  # NUL이 섞인 바이너리
        b"\xff\xfe" + b"\x00\xd8" * 2,  # UTF-16 BOM이지만 깨진 대리쌍
    ],
)
def test_binary_csv_is_rejected(tmp_path: Path, data: bytes) -> None:
    assert _rejected("req.csv", data, tmp_path).status == 415


def test_zip_with_spoofed_sizes_never_reaches_the_parser(tmp_path: Path) -> None:
    """선언 크기를 1바이트로 위조해도 실제로 풀어 세므로 막힌다 (#216 리뷰)."""
    bomb = _spoofed(_zip({"[Content_Types].xml": b"A" * (8 * MIB)}), declared=1)
    assert len(bomb) < 64 * 1024

    assert _rejected("req.xlsx", bomb, tmp_path, unzipped=1 * MIB).status == 413
    # 한도 안이어도 선언 크기와 실제 크기가 다르면 깨진 파일이다
    assert _rejected("req.xlsx", bomb, tmp_path).status == 415


def test_zip_with_a_broken_central_directory_is_415(tmp_path: Path) -> None:
    """끝 레코드만 멀쩡한 zip도 서버 오류(500)가 아니라 입력 오류다 (#216 리뷰)."""
    data = bytearray(_zip({"[Content_Types].xml": b"<Types/>"}))
    central = data.index(b"PK\x01\x02")
    data[central : central + 4] = b"XXXX"
    assert zipfile.is_zipfile(BytesIO(bytes(data)))

    assert _rejected("req.xlsx", bytes(data), tmp_path).status == 415


def test_hwp_with_the_ole_signature_is_accepted(tmp_path: Path) -> None:
    """.hwp(HWP 5.0)는 OLE 복합 문서다. 안의 내용(암호·배포용 등)은 파서가 판정한다 (#24)."""
    data = bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 504

    stored = _save("정의서.HWP", data, tmp_path)

    assert stored.file_format == "hwp"
    assert stored.storage_ref.endswith(".hwp")


@pytest.mark.parametrize("data", [b"<hwpml/>", b"PK\x03\x04" + b"\x00" * 26, b"d0cf11e0"])
def test_hwp_without_the_ole_signature_is_415(tmp_path: Path, data: bytes) -> None:
    """확장자만 .hwp로 바꾼 파일(HWPX·텍스트 등)을 파서에 넘기지 않는다."""
    error = _rejected("req.hwp", data, tmp_path)

    assert error.status == 415
    assert ".hwp 형식이 아닙니다" in error.message


def test_valid_zip_within_the_limit_is_accepted(tmp_path: Path) -> None:
    data = _zip({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<workbook/>" * 100})

    assert _save("req.xlsx", data, tmp_path).file_format == "xlsx"


def _patched_central(data: bytes, offset: int, value: bytes) -> bytes:
    patched = bytearray(data)
    central = patched.index(b"PK\x01\x02")
    patched[central + offset : central + offset + len(value)] = value
    return bytes(patched)


@pytest.mark.parametrize(
    "corrupt",
    [
        # UTF-8 표시(일반 비트 11)를 켜고 파일명을 UTF-8이 아닌 바이트로 바꿈 → UnicodeDecodeError
        lambda d: _patched_central(
            _patched_central(d, 8, struct.pack("<H", 0x0800)), 46, b"\xff\xfe\xfd\xfc\xfb"
        ),
        # 필요한 해제 버전을 지원 범위 밖(100)으로 → NotImplementedError
        lambda d: _patched_central(d, 6, struct.pack("<H", 100)),
    ],
    ids=["invalid-utf8-name", "unsupported-version"],
)
def test_zip_encoding_and_version_problems_are_415(tmp_path: Path, corrupt) -> None:  # type: ignore[no-untyped-def]
    """zip 파싱의 인코딩·지원 범위 예외도 서버 오류가 아니라 입력 오류다 (#216 리뷰)."""
    data = corrupt(_zip({"a.xml": b"<Types/>"}))

    assert _rejected("req.xlsx", data, tmp_path).status == 415
