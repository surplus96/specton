"""업로드 저장 (06·11 문서). 실패하면 파일과 빈 run 폴더를 남기지 않는다."""

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
