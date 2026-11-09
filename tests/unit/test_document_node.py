"""문서 생성 가지의 기능 명세서 PDF 후보 (#17, 엔진 #243).

PDF를 켜면 같은 revision의 기능 명세서 Markdown과 함께 PDF 후보를 만들되 승인 전에는 비공개다.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from specton.codegen.normalize_step import normalize_design
from specton.contracts import DesignState, Entity, Function, Normalized, Requirement, VersionInfo
from specton.document_node import document_node
from specton.graph import initial_state
from specton.packs.build import DEFAULT_ROOT, read_yaml


@dataclass(frozen=True)
class _Pdf:
    pdf: bytes = b"%PDF-1.7\nfixture\n%%EOF"
    warnings: tuple[str, ...] = ()
    blocked_urls: tuple[str, ...] = ()


@pytest.fixture
def design() -> DesignState:
    state = DesignState(
        run_id="00000000-0000-4000-8000-000000000017", revision=1,
        versions=VersionInfo(pack_id="inventory", pack_version=str(
            read_yaml(DEFAULT_ROOT / "inventory/manifest.yaml")["version"])),
        requirements=(Requirement(
            id="REQ-01", source_ref={"file_format": "csv", "row": 2}, type="FR",
            text="창고를 등록한다", draft_text="창고를 등록한다", analysis_version=1,
        ),),
        functions=(Function(
            id="FUNC-01", name="창고 등록", description="창고를 등록한다", req_ids=("REQ-01",),
            entity_ops=({"entity_id": "ENT-01", "operations": ("C", "R")},),
        ),),
        entities=(Entity.model_validate({
            "id": "ENT-01", "pack": "inventory", "name": "창고", "description": "창고",
            "req_ids": ["REQ-01"], "attributes": [{
                "id": "ATTR-01", "name": "창고코드", "data_type": "varchar", "length": 10,
                "is_key": True, "nullable": False, "req_ids": ["REQ-01"],
            }],
        }),),
    )  # fmt: skip
    result = normalize_design(state)
    assert isinstance(result, Normalized), result
    return state.evolve(normalized=result.model)


def _formats(update: dict[str, object]) -> dict[tuple[str, str], bool]:
    files = update["generated_artifacts"]
    assert isinstance(files, dict)
    return {(i["ref"].kind, i["ref"].file_format): i["ref"].approved for i in files.values()}


def test_pdf_candidate_is_made_next_to_the_markdown_and_kept_private(
    design: DesignState, tmp_path: Path
) -> None:
    seen: list[DesignState] = []

    def render(state: DesignState) -> _Pdf:
        seen.append(state)
        return _Pdf(warnings=("표 글자가 작습니다",))

    update = dict(document_node(tmp_path, pdf=render)(initial_state(design)))
    formats = _formats(update)
    assert formats[("functions", "md")] is False
    assert formats[("functions", "pdf")] is False  # 승인 전 비공개
    assert ("rtm", "xlsx") in formats and ("rtm", "csv") in formats
    assert seen == [design]
    assert update["notes"] == (
        {"message": "표 글자가 작습니다", "payload": {"kind": "functions", "file_format": "pdf"}},
    )


def test_without_functions_the_renderer_is_not_called(design: DesignState, tmp_path: Path) -> None:
    def render(state: DesignState) -> _Pdf:
        pytest.fail("기능이 없으면 기능 명세서 PDF를 만들지 않는다")

    update = dict(document_node(tmp_path, pdf=render)(initial_state(design.evolve(functions=()))))
    assert not any(kind == "functions" for kind, _ in _formats(update))
    assert "notes" not in update


def test_without_a_renderer_only_the_markdown_is_made(design: DesignState, tmp_path: Path) -> None:
    update = dict(document_node(tmp_path)(initial_state(design)))
    formats = _formats(update)
    assert ("functions", "md") in formats and ("functions", "pdf") not in formats
    assert "notes" not in update
