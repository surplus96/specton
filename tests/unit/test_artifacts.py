"""파일을 완성한 뒤 체크포인트에 인계한다. 과거 파일과 승인 여부는 바이트 해시와 별개다."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from specton.artifacts import artifact_key, write_artifact
from specton.contracts import DesignState
from specton.model_hash import model_hash
from specton.persistence.db import checkpoint_serde


def test_repeated_writes_share_an_immutable_path_and_survive_strict_serialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = DesignState(run_id=str(uuid4()))
    content = b"CREATE TABLE fixture (id bigint PRIMARY KEY);"
    first = write_artifact(tmp_path, state, "ddl", "sql", content)
    path = tmp_path / first["storage_ref"]
    before = path.stat()
    approved = write_artifact(tmp_path, state, "ddl", "sql", content, approved=True)
    other = write_artifact(tmp_path, state, "ddl", "sql", content + b"\n")
    revised = write_artifact(tmp_path, state.evolve(revision=1), "ddl", "sql", content)

    assert first["ref"].hash == hashlib.sha256(content).hexdigest()
    assert first["storage_ref"] == approved["storage_ref"]
    assert path.stat().st_ino == before.st_ino
    assert path.read_bytes() == content
    assert len({first["storage_ref"], other["storage_ref"], revised["storage_ref"]}) == 3
    assert first["model_hash"] == approved["model_hash"] == model_hash(state)
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    packet = {artifact_key(first["ref"]): first}
    serde = checkpoint_serde()
    assert serde.loads_typed(serde.dumps_typed(packet)) == packet


def test_model_hash_keeps_the_existing_snapshot_algorithm() -> None:
    state = DesignState(run_id=str(uuid4()))
    legacy_payload = {"requirements": [], "functions": [], "entities": [], "relationships": []}
    expected = hashlib.sha256(
        json.dumps(legacy_payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    assert model_hash(state) == expected
    assert model_hash(state.evolve(status="exporting", revision=1)) == expected


def test_existing_corrupted_content_is_never_overwritten(tmp_path: Path) -> None:
    state = DesignState(run_id=str(uuid4()))
    item = write_artifact(tmp_path, state, "ddl", "sql", b"original")
    path = tmp_path / item["storage_ref"]
    path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="해시"):
        write_artifact(tmp_path, state, "ddl", "sql", b"original")
    assert path.read_bytes() == b"corrupted"


def test_symlink_outside_storage_is_rejected_before_writing(tmp_path: Path) -> None:
    state = DesignState(run_id=str(uuid4()))
    root = tmp_path / "storage"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / state.run_id).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="저장소"):
        write_artifact(root, state, "ddl", "sql", b"fixture")
    assert list(outside.iterdir()) == []


def test_unsupported_kind_format_is_rejected_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="형식"):
        write_artifact(tmp_path, DesignState(run_id=str(uuid4())), "ddl", "pdf", b"fixture")
    assert list(tmp_path.iterdir()) == []
