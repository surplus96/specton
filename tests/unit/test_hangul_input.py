"""한글 입력을 실제 엔진으로 끝까지 읽는다 (#24, TC-F21).

비공개 원문 없이 돌도록 상세표 하나를 담은 최소 HWPX를 시험 안에서 만든다(OWPML zip).
엔진을 못 불러오는 환경에서는 `test_ingest_hangul`과 같은 기준으로 건너뛴다.
CI는 `hangul engine tests` 단계에서 시스템 libfreetype을 먼저 불러온 채 돌린다.
"""

import zipfile
from pathlib import Path

from test_ingest_hangul import _import_engine

from specton import parse_node as parse_module
from specton.contracts import DesignState
from specton.graph import DocumentRef, initial_state
from specton.ingest.hangul import read_hangul
from specton.parse_node import parse_node

_NS = (
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:opf="http://www.idpf.org/2007/opf/"'
)
_CONTAINER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container"><ocf:rootfiles>'
    '<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
    "</ocf:rootfiles></ocf:container>"
)
_PACKAGE = (
    f'<?xml version="1.0" encoding="UTF-8"?><opf:package {_NS}><opf:manifest>'
    '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
    '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
    '</opf:manifest><opf:spine><opf:itemref idref="header"/><opf:itemref idref="section0"/>'
    "</opf:spine></opf:package>"
)
_HEADER = (
    f'<?xml version="1.0" encoding="UTF-8"?><hh:head {_NS} version="1.4" secCnt="1">'
    "<hh:refList/></hh:head>"
)

# 상세표 한 개: 라벨 칸 → 같은 행 오른쪽 값 칸. 원문 기호(①·•·가.)를 값에 그대로 둔다
DETAIL = (
    ("요구사항 고유번호", "SFR-001"),
    ("요구사항 명칭", "입고 등록"),
    ("정의", "① 입고 예정 정보를 등록한다"),
    ("세부내용", "• 품목·수량을 입력한다\n가. 저장 전에 확인한다"),
)


def _cell(row: int, col: int, text: str) -> str:
    paragraphs = "".join(
        f'<hp:p id="0" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>{line}</hp:t>'
        "</hp:run></hp:p>"
        for line in text.split("\n")
    )
    return (
        f"<hp:tc><hp:subList>{paragraphs}</hp:subList>"
        f'<hp:cellAddr colAddr="{col}" rowAddr="{row}"/><hp:cellSpan colSpan="1" rowSpan="1"/>'
        '<hp:cellSz width="5000" height="1000"/></hp:tc>'
    )


def _minimal_hwpx(path: Path, rows: tuple[tuple[str, str], ...] = DETAIL) -> Path:
    """상세표 하나만 든 최소 HWPX.

    한글이 만든 파일의 모든 요소를 담지는 않는다(엔진이 읽는 만큼).
    """
    table = f'<hp:tbl rowCnt="{len(rows)}" colCnt="2">' + "".join(
        f"<hp:tr>{_cell(i, 0, label)}{_cell(i, 1, value)}</hp:tr>"
        for i, (label, value) in enumerate(rows)
    )
    section = (
        f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {_NS}>'
        '<hp:p id="0" paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0">'
        f"{table}</hp:tbl></hp:run></hp:p></hs:sec>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip")  # 압축하지 않는 첫 항목
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("Contents/content.hpf", _PACKAGE)
        z.writestr("Contents/header.xml", _HEADER)
        z.writestr("Contents/section0.xml", section)
    return path


def test_real_hwpx_keeps_original_symbols_and_location(tmp_path: Path) -> None:
    """원문 기호(①·•·가.)와 줄바꿈을 고치지 않고, 위치는 구역·문단·표·고유번호 값 칸이다."""
    _import_engine()
    path = _minimal_hwpx(tmp_path / "정의서.hwpx")

    [req] = read_hangul(path, "doc-1").requirements

    assert req.source_id == "SFR-001"
    assert req.extraction_status == "pass"
    expected = "① 입고 예정 정보를 등록한다\n• 품목·수량을 입력한다\n가. 저장 전에 확인한다"
    assert req.source_text == expected
    ref = req.source_ref
    location = (ref.file_format, ref.section, ref.paragraph, ref.table, ref.cell)
    assert location == ("hwpx", 0, 0, 0, "B1")


def test_parse_node_reads_an_uploaded_hwpx(tmp_path: Path) -> None:
    """업로드 저장 이름(`<문서 ID>.hwpx`) 그대로 parse 노드가 한글 파서로 읽는다."""
    _import_engine()
    _minimal_hwpx(tmp_path / "doc-1.hwpx")
    doc = DocumentRef(document_id="doc-1", file_format="hwpx", storage_ref="doc-1.hwpx")

    state = initial_state(DesignState(run_id="run-1"), (doc,))
    design: DesignState = parse_node(tmp_path)(state)["design"]

    [block] = design.source_requirements
    assert (block.document_id, block.block_id) == ("doc-1", "SFR-001")
    assert block.source_ref.file_format == "hwpx"
    assert block.source_text is not None and block.source_text.startswith("① ")


def test_hwp_and_hwpx_go_to_the_same_hangul_reader() -> None:
    """.hwp는 HWPX로 바꾸지 않고 같은 파서로 읽는다. 위치 형식만 hwp로 적는다(파서 시험)."""
    assert parse_module._READERS["hwp"] is read_hangul
    assert parse_module._READERS["hwpx"] is read_hangul
