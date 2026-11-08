"""#17: 실제 팩 정리 → DDL 생성 → 사전검사. DB·LLM·파일 게시 없이 검증한다."""

import hashlib
import shutil
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
import yaml

from specton import ddl_adapter
from specton.artifacts import artifact_key
from specton.codegen.ddl import DdlResult
from specton.codegen.model import Normalized
from specton.codegen.normalize_step import normalize_design
from specton.contracts import DesignState, Entity, Relationship, Requirement, VersionInfo
from specton.ddl_adapter import create_ddl_artifact, prepare_ddl
from specton.model_hash import model_hash
from specton.packs.build import DEFAULT_ROOT, read_yaml
from specton.persistence.db import checkpoint_serde
from specton.validate import allowed_sql


def _design(pack: str = "inventory") -> DesignState:
    specs = (
        (("창고", "창고코드", 10), ("설비", "설비코드", 10))
        if pack == "inventory"
        else (("설비", "설비코드", 10), ("고장접수", "접수번호", 20))
    )
    return DesignState(
        run_id="00000000-0000-4000-8000-000000000017",
        versions=VersionInfo(
            pack_id=pack,
            pack_version=str(read_yaml(DEFAULT_ROOT / pack / "manifest.yaml")["version"]),
        ),
        requirements=(
            Requirement(
                id="REQ-01", source_ref={"file_format": "csv", "row": 2}, type="FR",
                text="한 내역은 한 상위 항목에 연결된다.",
                draft_text="한 내역은 한 상위 항목에 연결된다.",
                analysis_version=1,
            ),
        ),
        entities=tuple(
            Entity.model_validate({
                "id": f"ENT-{index}", "pack": pack, "name": name, "description": name,
                "req_ids": ["REQ-01"], "attributes": [{
                    "id": f"ATTR-{index}", "name": key, "data_type": "varchar", "length": length,
                    "is_key": True, "nullable": False, "req_ids": ["REQ-01"],
                }],
            }) for index, (name, key, length) in enumerate(specs, 1)
        ),
        relationships=(
            Relationship(
                id="REL-01", parent="ENT-1", child="ENT-2", cardinality="1:N", optional=False,
                rationale="REQ-01 근거", req_ids=["REQ-01"],
            ),
        ),
    )  # fmt: skip


def _normalized(design: DesignState, *, root: Path = DEFAULT_ROOT) -> DesignState:
    result = normalize_design(design, root=root)
    assert isinstance(result, Normalized), result
    return design.evolve(normalized=result.model)


@pytest.fixture
def design() -> DesignState:
    return _normalized(_design())


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
def test_real_pack_to_identical_checked_bytes_without_mutating_state(pack: str) -> None:
    design = _normalized(_design(pack))
    before = design.model_dump(mode="json")

    prepared = prepare_ddl(design)

    assert prepared.sql_bytes == prepared.generation.sql.encode("utf-8")
    assert prepared.validation.sql_sha256 == hashlib.sha256(prepared.sql_bytes).hexdigest()
    assert (prepared.generation.pack, prepared.generation.pack_version) == (
        design.versions.pack_id,
        design.versions.pack_version,
    )
    assert prepared.generation.target == prepared.validation.target
    assert b"CREATE TABLE" in prepared.sql_bytes and b"ADD FOREIGN KEY" in prepared.sql_bytes
    assert prepared.generation.validation_state == prepared.validation.state == "unverified"
    assert [s.state for s in prepared.validation.stages] == [
        "passed",
        "passed",
        "not_run",
        "not_run",
        "not_run",
    ]
    assert design.model_dump(mode="json") == before
    assert prepare_ddl(design) == prepared
    with pytest.raises(FrozenInstanceError):
        prepared.sql_bytes = b"changed"  # type: ignore[misc]


def test_missing_normalized_model_stops_before_reading_packs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="정리 결과가 없습니다"):
        prepare_ddl(_design(), root=tmp_path)


@pytest.mark.parametrize(
    "changes", [{"pack_id": "maintenance"}, {"pack_version": "other"}, {"pack_version": None}]
)
def test_different_run_pack_cannot_reuse_normalized_model(
    design: DesignState, tmp_path: Path, changes: dict[str, Any]
) -> None:
    changed = design.evolve(versions=design.versions.evolve(**changes))
    with pytest.raises(ValueError, match="팩·버전이 다릅니다"):
        prepare_ddl(changed, root=tmp_path)


def test_uses_identifier_limit_from_selected_root(design: DesignState, tmp_path: Path) -> None:
    common = tmp_path / "common"
    common.mkdir()
    naming = read_yaml(DEFAULT_ROOT / "common/naming.yaml")
    naming["physical_name"]["max_bytes"] = 4
    (common / "naming.yaml").write_text(
        yaml.safe_dump(naming, allow_unicode=True), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="바이트"):
        prepare_ddl(design, root=tmp_path)


def test_missing_pack_config_is_not_replaced_by_default(
    design: DesignState, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        prepare_ddl(design, root=tmp_path)


def test_real_junction_and_self_reference_keep_their_sql(tmp_path: Path) -> None:
    for pack in ("common", "inventory"):
        shutil.copytree(DEFAULT_ROOT / pack, tmp_path / pack)
    naming_path = tmp_path / "common/naming.yaml"
    naming = read_yaml(naming_path)
    naming["column"]["self_reference_prefix"] = "상위"
    naming_path.write_text(yaml.safe_dump(naming, allow_unicode=True), encoding="utf-8")
    design = _design()
    design = design.evolve(relationships=(
        *design.relationships,
        Relationship(
            id="REL-02", parent="ENT-2", child="ENT-2", cardinality="1:N", optional=True,
            rationale="선택 자기참조", req_ids=["REQ-01"],
        ),
        Relationship(
            id="REL-03", parent="ENT-1", child="ENT-2", cardinality="N:M", optional=False,
            rationale="다대다 연결", req_ids=["REQ-01"],
        ),
    ))  # fmt: skip

    prepared = prepare_ddl(_normalized(design, root=tmp_path), root=tmp_path)

    assert prepared.sql_bytes.count(b"CREATE TABLE") == 3
    assert prepared.sql_bytes.count(b"ADD FOREIGN KEY") == 4
    assert b'"up_eqpm_cd"' in prepared.sql_bytes
    assert prepared.validation.state == "unverified"


def test_composite_foreign_key_survives_generation_and_precheck() -> None:
    design = _design()
    parent, child = design.entities
    name_key = parent.attributes[0].evolve(id="ATTR-name", name="창고명", length=200)
    design = design.evolve(
        entities=(parent.evolve(attributes=(*parent.attributes, name_key)), child)
    )

    prepared = prepare_ddl(_normalized(design))

    assert (
        b'FOREIGN KEY ("wrhus_cd", "wrhus_nm") REFERENCES "wrhus" ("wrhus_cd", "wrhus_nm")'
        in prepared.sql_bytes
    )
    assert prepared.validation.state == "unverified"


@pytest.mark.parametrize("suffix", ["\nCOMMIT;\n", "\nCREATE TABLE (\n"])
def test_sql_failure_preserves_exact_bytes_and_failed_stage(
    design: DesignState, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    generate = ddl_adapter.generate_ddl

    def changed_sql(*args: Any, **kwargs: Any) -> DdlResult:
        result = generate(*args, **kwargs)
        return DdlResult.model_validate({**result.model_dump(), "sql": result.sql + suffix})

    monkeypatch.setattr(ddl_adapter, "generate_ddl", changed_sql)
    prepared = prepare_ddl(design)

    assert prepared.sql_bytes.endswith(suffix.encode())
    assert prepared.validation.sql_sha256 == hashlib.sha256(prepared.sql_bytes).hexdigest()
    assert prepared.validation.state == "failed"
    assert any(s.state == "failed" for s in prepared.validation.stages[:2])
    assert all(s.state == "not_run" for s in prepared.validation.stages[2:])


def test_checker_outage_remains_error(design: DesignState, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("private diagnostic")

    monkeypatch.setattr(allowed_sql, "parse_sql", unavailable)
    prepared = prepare_ddl(design)

    assert prepared.validation.state == "error"
    assert prepared.validation.stages[0].state == "error"
    assert prepared.validation.stages[0].problems[0].detail == "RuntimeError"
    assert all(s.state == "not_run" for s in prepared.validation.stages[1:])


def test_generator_error_is_not_made_into_a_validation_result(
    design: DesignState, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> DdlResult:
        raise ValueError("generator failed")

    monkeypatch.setattr(ddl_adapter, "generate_ddl", unavailable)
    with pytest.raises(ValueError, match="generator failed"):
        prepare_ddl(design)


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
def test_ddl_file_handoff_keeps_checked_bytes_and_current_model(
    pack: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    design = _normalized(_design(pack)).evolve(revision=2)
    before = design.model_dump(mode="json")

    result = create_ddl_artifact(design, storage_dir=tmp_path)

    item = result.generated
    ref = item["ref"]
    assert (tmp_path / item["storage_ref"]).read_bytes() == result.prepared.sql_bytes
    assert ref.hash == result.prepared.validation.sql_sha256
    assert ref.hash == hashlib.sha256(result.prepared.sql_bytes).hexdigest()
    assert (ref.kind, ref.file_format, ref.revision, ref.approved) == ("ddl", "sql", 2, False)
    assert item["storage_ref"] == f"{design.run_id}/r2/ddl-{ref.hash}.sql"
    assert item["model_hash"] == model_hash(design)
    assert result.prepared.validation.state == "unverified"
    assert design.model_dump(mode="json") == before
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    packet = {artifact_key(ref): item}
    serde = checkpoint_serde()
    assert serde.loads_typed(serde.dumps_typed(packet)) == packet


def test_repeated_ddl_files_keep_path_but_track_model_and_revision(
    design: DesignState, tmp_path: Path
) -> None:
    first = create_ddl_artifact(design, storage_dir=tmp_path)
    path = tmp_path / first.generated["storage_ref"]
    inode = path.stat().st_ino
    repeated = create_ddl_artifact(design, storage_dir=tmp_path)
    requirement = design.requirements[0].evolve(text="동일한 SQL을 쓰는 변경된 요구사항 설명")
    changed = design.evolve(requirements=(requirement,))
    updated = create_ddl_artifact(changed, storage_dir=tmp_path)
    revised = create_ddl_artifact(design.evolve(revision=1), storage_dir=tmp_path)

    assert repeated.generated == first.generated
    assert path.stat().st_ino == inode
    assert updated.generated["storage_ref"] == first.generated["storage_ref"]
    assert updated.generated["model_hash"] == model_hash(changed)
    assert updated.generated["model_hash"] != first.generated["model_hash"]
    assert revised.generated["ref"].hash == first.generated["ref"].hash
    assert revised.generated["ref"].revision == 1
    assert revised.generated["storage_ref"] != first.generated["storage_ref"]
    assert len(list(tmp_path.rglob("*.sql"))) == 2


@pytest.mark.parametrize("failure", ["syntax", "forbidden", "checker"])
def test_failed_or_error_sql_is_stored_as_draft_with_its_result(
    design: DesignState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    if failure == "checker":

        def unavailable(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("private diagnostic")

        monkeypatch.setattr(allowed_sql, "parse_sql", unavailable)
    else:
        generate = ddl_adapter.generate_ddl

        def changed_sql(*args: Any, **kwargs: Any) -> DdlResult:
            result = generate(*args, **kwargs)
            suffix = "\nCOMMIT;\n" if failure == "forbidden" else "\nCREATE TABLE (\n"
            return DdlResult.model_validate({**result.model_dump(), "sql": result.sql + suffix})

        monkeypatch.setattr(ddl_adapter, "generate_ddl", changed_sql)

    result = create_ddl_artifact(design, storage_dir=tmp_path)

    assert result.prepared.validation.state == ("error" if failure == "checker" else "failed")
    assert result.generated["ref"].approved is False
    content = (tmp_path / result.generated["storage_ref"]).read_bytes()
    assert content == result.prepared.sql_bytes
    assert hashlib.sha256(content).hexdigest() == result.prepared.validation.sql_sha256


@pytest.mark.parametrize(
    "failure, error_type, message",
    [
        ("missing_model", ValueError, "정리 결과"),
        ("generator", ValueError, "generator failed"),
        ("pack", FileNotFoundError, r"naming\.yaml"),
        ("hash", ValueError, "해시"),
    ],
)
def test_invalid_ddl_preparation_creates_no_file(
    design: DesignState,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    error_type: type[Exception],
    message: str,
) -> None:
    root = DEFAULT_ROOT
    if failure == "missing_model":
        design = design.evolve(normalized=None)
    elif failure == "generator":

        def unavailable(*args: Any, **kwargs: Any) -> DdlResult:
            raise ValueError("generator failed")

        monkeypatch.setattr(ddl_adapter, "generate_ddl", unavailable)
    elif failure == "pack":
        root = tmp_path / "missing-pack"
    else:
        check = ddl_adapter.check_allowed_sql

        def mismatched(sql: bytes) -> allowed_sql.SqlValidation:
            return check(sql).model_copy(update={"sql_sha256": "0" * 64})

        monkeypatch.setattr(ddl_adapter, "check_allowed_sql", mismatched)

    storage = tmp_path / "storage"
    with pytest.raises(error_type, match=message):
        create_ddl_artifact(design, storage_dir=storage, root=root)
    assert not storage.exists()


def test_corrupt_ddl_file_is_not_overwritten(design: DesignState, tmp_path: Path) -> None:
    first = create_ddl_artifact(design, storage_dir=tmp_path)
    path = tmp_path / first.generated["storage_ref"]
    path.write_bytes(b"corrupted")

    with pytest.raises(ValueError, match="해시"):
        create_ddl_artifact(design, storage_dir=tmp_path)

    assert path.read_bytes() == b"corrupted"


def test_ddl_file_write_error_propagates(
    design: DesignState, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> None:
        raise OSError("write failed")

    monkeypatch.setattr(ddl_adapter, "write_artifact", unavailable)
    with pytest.raises(OSError, match="write failed"):
        create_ddl_artifact(design, storage_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []
