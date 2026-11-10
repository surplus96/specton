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

    update = parse_node(tmp_path)(initial_state(DesignState(run_id="run-1"), (doc,)))
    design = update["design"]

    assert [b.block_id for b in design.source_requirements] == ["xlsx:요구사항:2"]
    assert update["notes"] == ()


@pytest.mark.parametrize("header_only", [False, True])
def test_skipped_sheets_are_left_as_a_note_for_the_extraction_screen(
    tmp_path: Path, header_only: bool
) -> None:
    """표가 없거나 빈 표인 시트는 안내 한 줄이다 (#95 결론, docs/09 UI-02)."""
    book = Workbook()
    cover = book.active
    cover.title = "표지"
    cover.append(HEADER.split(",") if header_only else ["재고 관리 요구사항 정의서"])
    sheet = book.create_sheet("요구사항")
    sheet.append(HEADER.split(","))
    sheet.append(["SFR-001", "입고 등록", "입고를 등록한다"])
    book.save(tmp_path / "a.xlsx")
    doc = DocumentRef(document_id="doc-1", file_format="xlsx", storage_ref="a.xlsx")
    state = initial_state(DesignState(run_id="run-1"), (doc,))

    update = parse_node(tmp_path)(state)

    assert update["notes"] == (
        {
            "message": "요구사항을 읽지 않은 시트가 있습니다",
            "payload": {"info": "skipped_sheets", "document_id": "doc-1", "sheets": ["표지"]},
        },
    )
    assert [b.block_id for b in update["design"].source_requirements] == ["xlsx:요구사항:2"]


def test_skipped_sheet_notes_identify_each_document(tmp_path: Path) -> None:
    documents = []
    for n in (1, 2):
        book = Workbook()
        book.active.title = "표지"
        sheet = book.create_sheet("요구사항")
        sheet.append(HEADER.split(","))
        sheet.append([f"SFR-00{n}", "입고 등록", "입고를 등록한다"])
        book.save(tmp_path / f"{n}.xlsx")
        documents.append(
            DocumentRef(document_id=f"doc-{n}", file_format="xlsx", storage_ref=f"{n}.xlsx")
        )
    state = initial_state(DesignState(run_id="run-1"), tuple(documents))

    update = parse_node(tmp_path)(state)

    assert [n["payload"]["document_id"] for n in update["notes"]] == ["doc-1", "doc-2"]
    assert [n["payload"]["sheets"] for n in update["notes"]] == [["표지"], ["표지"]]


def test_csv_has_no_skipped_sheet_note(tmp_path: Path) -> None:
    doc = _write(tmp_path, "a.csv", f"{HEADER}\nSFR-001,입고 등록,입고를 등록한다\n")
    state = initial_state(DesignState(run_id="run-1"), (doc,))

    assert parse_node(tmp_path)(state)["notes"] == ()


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


def test_format_without_a_parser_ends_as_unreadable(tmp_path: Path) -> None:
    """파서가 없는 형식(PDF, 이번 범위 밖)은 읽지 못한 파일로 끝낸다. 한글은 #24로 읽는다."""
    doc = DocumentRef(document_id="doc-1", file_format="pdf", storage_ref="a.pdf")

    with pytest.raises(ExtractionFailedError, match="읽을 수 없는 형식"):
        _parse(tmp_path, doc)


def test_run_without_documents_is_an_internal_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="문서"):
        _parse(tmp_path)
