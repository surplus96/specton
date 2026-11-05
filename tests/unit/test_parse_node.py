"""#17 parse 노드: 업로드 문서를 형식별 파서(#115)로 읽어 원문 블록으로 둔다 (ADR-0015 결정 3)."""

from pathlib import Path

import pytest
from openpyxl import Workbook  # type: ignore[import-untyped]

from specton import parse_node as parse_module
from specton.contracts import DesignState
from specton.graph import DocumentRef, ExtractionFailedError, initial_state
from specton.ingest.tabular import TabularResult
from specton.parse_node import parse_node

HEADER = "요구사항 ID,요구사항명,상세 내용"


def _write(storage: Path, name: str, text: str) -> DocumentRef:
    (storage / name).write_text(text, encoding="utf-8")
    return DocumentRef(document_id="doc-1", file_format=name.rsplit(".", 1)[1], storage_ref=name)


def _parse(storage: Path, *documents: DocumentRef) -> DesignState:
    state = initial_state(DesignState(run_id="run-1"), documents)
    design: DesignState = parse_node(storage)(state)["design"]
    return design


def test_csv_rows_become_source_blocks_of_the_document(tmp_path: Path) -> None:
    doc = _write(
        tmp_path, "a.csv", f"{HEADER}\nSFR-001,입고 등록,입고를 등록한다\n,출고,출고한다\n"
    )

    design = _parse(tmp_path, doc)

    blocks = design.source_requirements
    assert [b.block_id for b in blocks] == ["csv:2", "csv:3"]
    assert {b.document_id for b in blocks} == {"doc-1"}
    assert [b.extraction_status for b in blocks] == ["pass", "review"]  # ID 없는 행은 review


def test_excel_sheet_rows_become_source_blocks(tmp_path: Path) -> None:
    book = Workbook()
    sheet = book.active
    sheet.title = "요구사항"
    sheet.append(HEADER.split(","))
    sheet.append(["SFR-001", "입고 등록", "입고를 등록한다"])
    book.save(tmp_path / "a.xlsx")
    doc = DocumentRef(document_id="doc-1", file_format="xlsx", storage_ref="a.xlsx")

    design = _parse(tmp_path, doc)

    assert [b.block_id for b in design.source_requirements] == ["xlsx:요구사항:2"]


def test_unreadable_file_ends_the_run_as_extraction_failed(tmp_path: Path) -> None:
    doc = _write(tmp_path, "a.csv", "이름,값\n가,1\n")  # 요구사항 표 머리글이 없다

    with pytest.raises(ExtractionFailedError) as caught:
        _parse(tmp_path, doc)

    assert caught.value.notice  # 파서가 만든 화면 안내를 그대로 넘긴다


def test_document_without_any_block_ends_the_run_as_extraction_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """파서가 원문 블록을 하나도 돌려주지 않으면 실행을 EXTRACTION_FAILED로 끝낸다.

    지금 표 파서는 빈 행도 블록으로 돌려줘(#10) 이 분기에 닿지 않는다. 다른 형식 파서를 위해 지킨다.
    """
    monkeypatch.setitem(parse_module._READERS, "csv", lambda path, doc_id: TabularResult(()))
    doc = _write(tmp_path, "a.csv", f"{HEADER}\nSFR-001,,\n")

    with pytest.raises(ExtractionFailedError):
        _parse(tmp_path, doc)


def test_row_without_text_becomes_a_review_block_without_source_text(tmp_path: Path) -> None:
    """이름·내용 칸이 모두 빈 행은 원문 문장 없는 review 블록이 된다 (#10). 실행은 끝내지 않고
    추출 확인(UI-02)에서 사용자가 제외한다."""
    doc = _write(tmp_path, "a.csv", f"{HEADER}\nSFR-001,,\n")

    [block] = _parse(tmp_path, doc).source_requirements

    assert block.source_text is None
    assert block.extraction_status == "review"
    assert block.notice


def test_hwpx_is_not_read_until_its_parser_exists(tmp_path: Path) -> None:
    """HWPX 파서는 #24에서 만든다. 그때까지 읽지 못한 파일로 끝낸다."""
    doc = DocumentRef(document_id="doc-1", file_format="hwpx", storage_ref="a.hwpx")

    with pytest.raises(ExtractionFailedError):
        _parse(tmp_path, doc)


def test_run_without_documents_is_an_internal_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="문서"):
        _parse(tmp_path)
