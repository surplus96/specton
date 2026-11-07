"""API 그래프가 지정한 공통 팩으로 실제 정리 실패를 분류한다. LLM은 호출하지 않는다."""

import shutil
from pathlib import Path

import pytest
import yaml
from langgraph.checkpoint.memory import InMemorySaver

from specton.api import main
from specton.config import Settings
from specton.contracts import DesignState, Entity, Requirement, VersionInfo
from specton.graph import DocumentRef, initial_state
from specton.packs.build import DEFAULT_ROOT, read_yaml
from specton.persistence.db import checkpoint_serde


@pytest.mark.parametrize("rule", ["RULE-03", "RULE-05"])
def test_api_graph_does_not_hide_missing_failure_severity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rule: str
) -> None:
    """사용자 pack_root에 심각도가 없으면 실행 오류다. 기본 팩의 값으로 대신하지 않는다."""
    root = tmp_path / "packs"
    for pack in ("common", "maintenance"):
        shutil.copytree(DEFAULT_ROOT / pack, root / pack)
    path = root / "common/rules.yaml"
    rules = read_yaml(path)
    for item in rules["rules"]:
        if item["id"] == rule:
            item["severity"] = None
    path.write_text(yaml.safe_dump(rules, allow_unicode=True), encoding="utf-8")
    (tmp_path / "req.csv").write_text(
        "요구사항 ID,요구사항명,상세 내용\nMNT-001,설비 등록,설비는 설비코드로 구분한다\n",
        encoding="utf-8",
    )
    requirement = Requirement(
        id="REQ-01", source_ref={"file_format": "csv", "row": 2}, type="FR",
        text="설비는 설비코드로 구분한다", draft_text="설비는 설비코드로 구분한다",
        analysis_version=1,
    )  # fmt: skip
    entity = Entity.model_validate({
        "id": "ENT-eq", "pack": "maintenance",
        "name": "설비" if rule == "RULE-03" else "사전미등록XYZ", "description": "설비",
        "req_ids": ["REQ-01"], "attributes": [{
            "id": "ATTR-eq", "name": "설비코드", "data_type": "varchar", "length": 10,
            "is_key": rule != "RULE-03", "nullable": False, "req_ids": ["REQ-01"],
        }],
    })  # fmt: skip
    monkeypatch.setattr(main, "openai_agent_nodes", lambda settings: {})
    settings = Settings(_env_file=None, openai_api_key=None, pack_root=root, storage_dir=tmp_path)
    graph = main.create_graph(settings, InMemorySaver(serde=checkpoint_serde()))
    design = DesignState(
        run_id="fixture", requirements=(requirement,), entities=(entity,),
        versions=VersionInfo(pack_id="maintenance", pack_version=str(
            read_yaml(root / "maintenance/manifest.yaml")["version"])),
    )  # fmt: skip
    document = DocumentRef(document_id="fixture-doc", file_format="csv", storage_ref="req.csv")
    with pytest.raises(ValueError, match=f"{rule}의 심각도"):
        graph.invoke(initial_state(design, (document,)), {"configurable": {"thread_id": "fixture"}})
