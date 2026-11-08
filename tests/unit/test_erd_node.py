"""#17: 실제 정리 모델 → ERD 파일·체크포인트 인계와 API 그래프 등록."""

import hashlib
from pathlib import Path
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from specton import erd_node as adapter
from specton.api import main
from specton.artifacts import artifact_key
from specton.codegen.erd import render_erd
from specton.codegen.normalize_step import normalize_design
from specton.config import Settings
from specton.contracts import (
    DesignState,
    Entity,
    Normalized,
    Relationship,
    Requirement,
    VersionInfo,
)
from specton.erd_node import create_erd_artifact, erd_node
from specton.graph import initial_state
from specton.model_hash import model_hash
from specton.packs.build import DEFAULT_ROOT, read_yaml
from specton.persistence.db import checkpoint_serde


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
        requirements=(Requirement(
            id="REQ-01", source_ref={"file_format": "csv", "row": 2}, type="FR",
            text="한 내역은 한 상위 항목에 연결된다.",
            draft_text="한 내역은 한 상위 항목에 연결된다.",
            analysis_version=1,
        ),),
        entities=tuple(Entity.model_validate({
            "id": f"ENT-{index}", "pack": pack, "name": name, "description": name,
            "req_ids": ["REQ-01"], "attributes": [{
                "id": f"ATTR-{index}", "name": key, "data_type": "varchar", "length": length,
                "is_key": True, "nullable": False, "req_ids": ["REQ-01"],
            }],
        }) for index, (name, key, length) in enumerate(specs, 1)),
        relationships=(Relationship(
            id="REL-01", parent="ENT-1", child="ENT-2", cardinality="1:N", optional=False,
            rationale="REQ-01 근거", req_ids=["REQ-01"],
        ),),
    )  # fmt: skip


def _normalized(pack: str = "inventory") -> DesignState:
    design = _design(pack)
    result = normalize_design(design)
    assert isinstance(result, Normalized), result
    return design.evolve(normalized=result.model)


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
def test_exact_mermaid_bytes_hash_revision_and_checkpoint_handoff(
    pack: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    design = _normalized(pack).evolve(revision=2)
    before = design.model_dump(mode="json")
    assert design.normalized is not None
    expected = render_erd(design.normalized, design.relationships).encode("utf-8")
    update = erd_node(tmp_path)(initial_state(design))
    assert set(update) == {"generated_artifacts"}
    ((key, generated),) = update["generated_artifacts"].items()
    ref = generated["ref"]
    assert key == artifact_key(ref) == "2:erd:mmd"
    assert (ref.kind, ref.file_format, ref.revision, ref.approved) == ("erd", "mmd", 2, False)
    assert ref.hash == hashlib.sha256(expected).hexdigest()
    assert (tmp_path / generated["storage_ref"]).read_bytes() == expected
    assert generated["model_hash"] == model_hash(design)
    assert design.model_dump(mode="json") == before
    monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
    serde = checkpoint_serde()
    assert serde.loads_typed(serde.dumps_typed(update)) == update


def test_repeated_generation_and_new_revision_keep_existing_files(tmp_path: Path) -> None:
    design = _normalized()
    first = create_erd_artifact(design, storage_dir=tmp_path)
    old_path = tmp_path / first["storage_ref"]
    before = old_path.read_bytes()
    assert create_erd_artifact(design, storage_dir=tmp_path) == first
    revised = create_erd_artifact(design.evolve(revision=1), storage_dir=tmp_path)
    assert revised["ref"].revision == 1
    assert revised["storage_ref"] != first["storage_ref"]
    assert old_path.read_bytes() == (tmp_path / revised["storage_ref"]).read_bytes() == before


@pytest.mark.parametrize("invalid", ["missing", "pack", "version", "relationship", "failed"])
def test_invalid_input_does_not_write_a_file(invalid: str, tmp_path: Path) -> None:
    design = _normalized()
    state = initial_state(design)
    if invalid == "missing":
        state["design"] = design.evolve(normalized=None)
    elif invalid in ("pack", "version"):
        changes = {"pack_id": "maintenance"} if invalid == "pack" else {"pack_version": "other"}
        state["design"] = design.evolve(versions=design.versions.evolve(**changes))
    elif invalid == "relationship":
        state["design"] = design.evolve(relationships=())
    else:
        state["normalization_failed"] = True
    with pytest.raises(ValueError):
        erd_node(tmp_path)(state)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("stage", ["render", "write"])
def test_generation_and_storage_errors_propagate(
    stage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise OSError("fixture failure")

    monkeypatch.setattr(
        adapter, "render_erd" if stage == "render" else "write_artifact", unavailable
    )
    with pytest.raises(OSError, match="fixture failure"):
        erd_node(tmp_path)(initial_state(_normalized()))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failed", [False, True])
def test_api_registers_real_erd_and_skips_it_after_normalization_failure(
    failed: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "openai_agent_nodes", lambda settings: {})
    monkeypatch.setattr(main, "parse_node", lambda root: lambda state: {})
    design = _design()
    if failed:
        entity = design.entities[0].evolve(name="사전미등록XYZ")
        design = design.evolve(entities=(entity, *design.entities[1:]))
    settings = Settings(
        _env_file=None,
        openai_api_key=None,
        pack_root=DEFAULT_ROOT,
        storage_dir=tmp_path,
    )
    graph = main.create_graph(settings, InMemorySaver(serde=checkpoint_serde()))
    result = graph.invoke(initial_state(design), {"configurable": {"thread_id": design.run_id}})
    assert result["design"].status == "awaiting_review"
    if failed:
        assert result["normalization_failed"] is True
        assert result["generated_artifacts"] == {}
        assert list(tmp_path.iterdir()) == []
    else:
        generated = result["generated_artifacts"]["0:erd:mmd"]
        normalized = result["design"].normalized
        assert normalized is not None
        assert (tmp_path / generated["storage_ref"]).read_bytes() == render_erd(
            normalized, result["design"].relationships
        ).encode("utf-8")
        assert result["design"].artifacts == (generated["ref"],)
