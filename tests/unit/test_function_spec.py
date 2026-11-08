"""#14: 기능 명세서 Markdown (docs/10 「출력 규격」, REQ-18)."""

import hashlib
from pathlib import Path

import pytest

from specton.artifacts import artifact_key
from specton.codegen.function_spec import DOCUMENT_INFO, document_info, render_function_spec
from specton.contracts import DesignState, Entity, Function, VersionInfo
from specton.function_spec_node import create_function_spec_artifact, function_spec_node
from specton.model_hash import model_hash

RUN_ID = "00000000-0000-4000-8000-000000000014"


def _entity(index: int, name: str, exemptions: list[dict[str, str]] | None = None) -> Entity:
    return Entity.model_validate({
        "id": f"ENT-{index:02}", "pack": "inventory", "name": name, "description": name,
        "req_ids": ["REQ-01"], "crud_exemptions": exemptions or [],
        "attributes": [{
            "id": f"ATTR-{index:02}", "name": f"{name}코드", "data_type": "varchar",
            "length": 10, "is_key": True, "nullable": False, "req_ids": ["REQ-01"],
        }],
    })  # fmt: skip


def _design(**changes: object) -> DesignState:
    functions = (
        Function(
            id="FUNC-01", name="입고 등록", description="입고 예정과 맞춰\n입고를 등록한다",
            priority="Must", priority_source="explicit", priority_rationale="원문 「필수」",
            req_ids=("REQ-01", "REQ-02"),
            entity_ops=(
                {"entity_id": "ENT-02", "operations": ("R", "C")},
                {"entity_id": "ENT-01", "operations": ("R",)},
            ),
        ),
        Function(
            id="FUNC-02", name="재고 조회 | 출력", description="재고를 조회한다",
            req_ids=("REQ-03",),
        ),
    )  # fmt: skip
    entities = (
        _entity(1, "창고"),
        _entity(2, "입고이력", [{"operation": "D", "reason": "이력은 지우지 않는다"}]),
    )
    state = DesignState(
        run_id=RUN_ID,
        revision=2,
        versions=VersionInfo(pack_id="inventory", pack_version="0.1.16"),
        functions=functions,
        entities=entities,
    )
    return state.evolve(**changes) if changes else state


def test_spec_has_document_info_list_details_and_crud() -> None:
    design = _design()

    text = render_function_spec(design)

    assert text.startswith("# 기능 명세서\n")
    assert f"| 모델 해시 (`model_hash`) | {model_hash(design)} |" in text
    assert "| 리비전 (`revision`) | 2 |" in text
    # 기능 목록: 우선순위와 출처, 미정
    assert "| FUNC-01 | 입고 등록 | Must (원문 명시) | REQ-01, REQ-02 |" in text
    assert "| FUNC-02 | 재고 조회 \\| 출력 | 미정 | REQ-03 |" in text
    # 상세: 줄바꿈은 한 줄로, 근거 없으면 -, CRUD는 C R U D 순서
    assert "- **설명:** 입고 예정과 맞춰 입고를 등록한다" in text
    assert "- **우선순위 근거:** 원문 「필수」" in text
    assert "- **엔티티 조작:** 입고이력(C R), 창고(R)" in text
    assert "### FUNC-02 재고 조회 | 출력" in text  # 표 밖에서는 이스케이프하지 않는다
    assert "- **우선순위 근거:** -" in text
    assert "- **엔티티 조작:** 없음" in text
    # CRUD 매트릭스: 엔티티는 설계 순서, 조작 없는 칸은 비움, 면제 근거
    assert "| 기능 | 창고 | 입고이력 |" in text
    assert "| FUNC-01 입고 등록 | R | C R |" in text
    assert "| FUNC-02 재고 조회 \\| 출력 |  |  |" in text
    assert "- 입고이력: D 없음 — 이력은 지우지 않는다" in text


def test_spec_uses_only_the_agreed_markdown() -> None:
    """PDF 엔진과 맞춘 문법만 쓴다: HTML 태그·셀 안 줄바꿈 없음, 표 행의 칸 수가 머리와 같다."""
    text = render_function_spec(_design())

    assert "<" not in text and ">" not in text
    assert "초안" not in text  # 승인본도 같은 바이트라 초안 표시는 넣지 않는다
    table: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.startswith("|"):
            table.append(line)
            continue
        if table:
            widths = {len(row.replace("\\|", "").split("|")) for row in table}
            assert len(widths) == 1, table
            table = []


def _gfm_cells(row: str) -> list[str]:
    """GFM 표 행을 칸으로 나눈다. 역슬래시는 다음 글자를 글자로 만든다(`\\|`는 칸 구분이 아님)."""
    cells, current, chars = [], "", iter(row.strip().strip("|"))
    for c in chars:
        if c == "\\":
            current += next(chars, "")
        elif c == "|":
            cells.append(current.strip())
            current = ""
        else:
            current += c
    return [*cells, current.strip()]


def test_backslash_and_pipe_in_names_keep_the_columns() -> None:
    """이름에 `\\|`가 있어도 칸이 갈라져 관련 요구사항이 잘리지 않는다 (#213 리뷰 P2)."""
    tricky = _design().functions[0].evolve(name="재고 \\| 출력", description="**굵게** `코드` \\끝")
    text = render_function_spec(_design(functions=(tricky,)))

    row = next(line for line in text.splitlines() if line.startswith("| FUNC-01 |"))
    assert _gfm_cells(row) == ["FUNC-01", "재고 \\| 출력", "Must (원문 명시)", "REQ-01, REQ-02"]
    crud = next(line for line in text.splitlines() if line.startswith("| FUNC-01 재고"))
    assert len(_gfm_cells(crud)) == 1 + len(_design().entities)
    # 굵게·코드 기호는 글자로 보이게 이스케이프한다 (R5 제안)
    assert "- **설명:** \\*\\*굵게\\*\\* \\`코드\\` \\\\끝" in text


def test_same_design_gives_the_same_bytes() -> None:
    assert render_function_spec(_design()) == render_function_spec(_design())


def test_document_info_names_match_the_erd_cover() -> None:
    """ERD PDF 표지와 같은 칸 이름 (#13·#14 합의)."""
    assert [key for _, key in DOCUMENT_INFO] == [
        "run_id", "revision", "model_hash", "pack", "pack_version",
    ]  # fmt: skip
    assert set(document_info(_design())) == {key for _, key in DOCUMENT_INFO}


def test_missing_pieces_are_rejected() -> None:
    with pytest.raises(ValueError, match="기능이 없습니다"):
        render_function_spec(_design(functions=()))
    unknown = (
        _design().functions[0].evolve(entity_ops=({"entity_id": "ENT-09", "operations": ("R",)},))
    )
    with pytest.raises(ValueError, match="설계에 없는 엔티티"):
        render_function_spec(_design(functions=(unknown,)))


def test_spec_without_entities_says_so() -> None:
    plain = _design().functions[1]
    text = render_function_spec(_design(functions=(plain,), entities=()))
    assert "## CRUD 매트릭스\n\n엔티티가 없습니다." in text


def test_artifact_is_saved_as_a_functions_markdown_draft(tmp_path: Path) -> None:
    design = _design()

    output = function_spec_node(tmp_path)({"design": design})  # type: ignore[typeddict-item]

    (generated,) = output["generated_artifacts"].values()
    ref = generated["ref"]
    assert (ref.kind, ref.file_format, ref.revision, ref.approved) == ("functions", "md", 2, False)
    assert artifact_key(ref) in output["generated_artifacts"]
    content = (tmp_path / generated["storage_ref"]).read_bytes()
    assert hashlib.sha256(content).hexdigest() == ref.hash
    assert content.decode("utf-8") == render_function_spec(design)
    assert generated["model_hash"] == model_hash(design)
    # 같은 내용을 다시 저장해도 같은 결과
    assert create_function_spec_artifact(design, storage_dir=tmp_path) == generated
