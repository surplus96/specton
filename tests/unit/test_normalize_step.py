"""모델 정리 연결 함수(`normalize_from_state`): 그래프 상태에서 팩을 꺼내 정리하고 결과를 돌려준다.

R1이 그래프 노드로 감쌀 때 받게 되는 값(성공·실패)을 고정한다. 입력은 실제 maintenance 팩
용어(설비코드·고장접수번호 등)로 만든 작은 설계 상태다.
"""

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from specton.codegen.model import Normalized, NormalizeFailed, ProblemCode
from specton.codegen.naming import DEFAULT_PACK_ROOT
from specton.codegen.normalize_step import normalize_from_state
from specton.contracts import DesignState, Entity, Relationship, Requirement
from specton.contracts.state import VersionInfo
from specton.packs.build import read_yaml

PACK = "maintenance"
PACK_VERSION = str(read_yaml(DEFAULT_PACK_ROOT / PACK / "manifest.yaml")["version"])


def _entity(entity_id: str, name: str, *attrs: dict[str, Any]) -> Entity:
    return Entity.model_validate(
        {
            "id": entity_id,
            "pack": PACK,
            "name": name,
            "description": f"{name} 정보",
            "attributes": [{"req_ids": ["REQ-01"], **a} for a in attrs],
            "req_ids": ["REQ-01"],
        }
    )


def _design(*, versions: VersionInfo | None = None, receipt_name: str = "고장접수") -> DesignState:
    # 길이는 팩 도메인과 같게 둔다 (설비코드: 코드C10, 고장접수번호: 번호V20)
    key = {"data_type": "varchar", "is_key": True, "nullable": False}
    return DesignState(
        run_id="run-1",
        versions=versions or VersionInfo(pack_id=PACK, pack_version=PACK_VERSION),
        requirements=[
            Requirement(
                id="REQ-01",
                source_ref={"file_format": "csv", "row": 2},
                text="한 접수는 한 설비에 대한 것이다.",
                draft_text="한 접수는 한 설비에 대한 것이다.",
                type="FR",
                analysis_version=1,
            )
        ],
        entities=[
            _entity(
                "ENT-eq", "설비", {"id": "ATTR-eq-cd", "name": "설비코드", "length": 10, **key}
            ),
            _entity(
                "ENT-rc",
                receipt_name,
                {"id": "ATTR-rc-no", "name": "고장접수번호", "length": 20, **key},
                {
                    "id": "ATTR-rc-dt",
                    "name": "접수일시",
                    "data_type": "timestamp",
                    "nullable": False,
                },
            ),
        ],
        relationships=[
            Relationship.model_validate(
                {
                    "id": "REL-01",
                    "parent": "ENT-eq",
                    "child": "ENT-rc",
                    "cardinality": "1:N",
                    "optional": False,
                    "rationale": '"한 접수는 한 설비에 대한 것이다." 접수마다 설비가 하나다.',
                    "req_ids": ["REQ-01"],
                }
            )
        ],
    )


def test_success_returns_tables_and_fk_with_recorded_pack() -> None:
    """R1이 성공 때 받는 값: `Normalized(model=...)`."""
    state = {"design": _design()}
    result = normalize_from_state(state)
    assert isinstance(result, Normalized), result
    model = result.model
    assert (model.pack, model.pack_version) == (PACK, PACK_VERSION)
    assert sorted(t.physical_name for t in model.tables) == ["bkdn_rcpt", "eqpm"]
    (fk,) = model.foreign_keys
    receipt = next(t for t in model.tables if t.entity_id == "ENT-rc")
    assert [c.physical_name for c in receipt.columns if c.id in fk.columns] == ["eqpm_cd"]
    assert fk.relationship_id == "REL-01" and fk.req_ids == ("REQ-01",)


def test_failure_returns_problems_only() -> None:
    """R1이 실패 때 받는 값: `NormalizeFailed(problems=...)`. 결과 모델은 없다."""
    result = normalize_from_state({"design": _design(receipt_name="수불문서")})
    assert isinstance(result, NormalizeFailed)
    assert [(p.code, p.decision, p.pending) for p in result.problems] == [
        (ProblemCode.UNRESOLVED_NAME, "D5", True)
    ]
    assert not hasattr(result, "model")


@pytest.mark.parametrize("receipt_name", ["고장접수", "수불문서"], ids=["success", "failure"])
def test_result_survives_checkpoint_save_and_restore(receipt_name: str) -> None:
    """그래프 체크포인트 직렬화로 저장했다 꺼내도 같은 값·같은 타입이다 (tuple 유지)."""
    result = normalize_from_state({"design": _design(receipt_name=receipt_name)})
    serde = JsonPlusSerializer()
    restored = serde.loads_typed(serde.dumps_typed(result))
    assert type(restored) is type(result)
    assert restored == result


def test_success_result_fits_the_design_state() -> None:
    """실제 정리 결과가 계약 검증을 그대로 통과해 `DesignState.normalized`에 담긴다 (#142)."""
    design = _design()
    result = normalize_from_state({"design": design})
    assert isinstance(result, Normalized)

    stored = design.evolve(normalized=result.model)

    assert stored.normalized == result.model


def test_input_state_is_not_changed() -> None:
    design = _design()
    before = design.model_dump()
    normalize_from_state({"design": design})
    assert design.model_dump() == before


def test_missing_pack_is_an_execution_error() -> None:
    """설계 노드(#121)와 같이 팩이 없으면 정리하지 않고 예외로 멈춘다."""
    with pytest.raises(ValueError, match="팩이 정해지지 않았습니다"):
        normalize_from_state({"design": _design(versions=VersionInfo())})


def test_missing_pack_version_is_an_execution_error() -> None:
    """실행 때 어떤 버전이었는지 모르면 지금 팩 파일 버전으로 메우지 않고 멈춘다."""
    with pytest.raises(ValueError, match="버전이 없습니다"):
        normalize_from_state({"design": _design(versions=VersionInfo(pack_id=PACK))})


def test_recorded_pack_version_different_from_pack_files_is_not_normalized() -> None:
    """다른 사전으로 정리하면 같은 입력이라도 결과가 달라질 수 있어 멈춘다."""
    design = _design(versions=VersionInfo(pack_id=PACK, pack_version="0.0.0-old"))
    result = normalize_from_state({"design": design})
    assert isinstance(result, NormalizeFailed)
    assert [(p.code, p.target) for p in result.problems] == [
        (ProblemCode.PACK_MISMATCH, "versions.pack_version")
    ]


def _self_reference(design: DesignState) -> DesignState:
    """설비의 상위 설비 관계(자기참조, 선택)를 더한 설계 상태."""
    rel = Relationship.model_validate(
        {
            "id": "REL-02",
            "parent": "ENT-eq",
            "child": "ENT-eq",
            "cardinality": "1:N",
            "optional": True,
            "rationale": '"한 접수는 한 설비에 대한 것이다." 상위 설비가 없는 설비도 있다.',
            "req_ids": ["REQ-01"],
        }
    )
    return design.model_copy(update={"relationships": [*design.relationships, rel]})


def test_self_reference_prefix_is_read_from_pack_files_on_the_graph_path(tmp_path: Path) -> None:
    """그래프 경로도 접두어를 naming.yaml column.self_reference_prefix에서 읽는다 (#11).

    값이 빈칸(미정)이면 막히고, 값이 있으면 up_eqpm_cd가 생긴다. 실제 팩 값과 상관없이
    복사본에 값을 넣어 본다.
    """
    design = _self_reference(_design())
    for pack in ("common", PACK):
        shutil.copytree(DEFAULT_PACK_ROOT / pack, tmp_path / pack)
    path = tmp_path / "common/naming.yaml"
    naming = read_yaml(path)

    naming["column"]["self_reference_prefix"] = None
    path.write_text(yaml.safe_dump(naming, allow_unicode=True), encoding="utf-8")
    blocked = normalize_from_state({"design": design}, root=tmp_path)
    assert isinstance(blocked, NormalizeFailed)
    assert [p.code for p in blocked.problems] == [ProblemCode.NAMING_RULE_MISSING]

    naming["column"]["self_reference_prefix"] = "상위"
    path.write_text(yaml.safe_dump(naming, allow_unicode=True), encoding="utf-8")
    result = normalize_from_state({"design": design}, root=tmp_path)
    assert isinstance(result, Normalized), result
    equipment = next(t for t in result.model.tables if t.entity_id == "ENT-eq")
    assert [c.physical_name for c in equipment.columns] == ["eqpm_cd", "up_eqpm_cd"]


def test_state_without_design_state_is_rejected() -> None:
    with pytest.raises(TypeError, match="DesignState"):
        normalize_from_state({"design": {"run_id": "run-1"}})
