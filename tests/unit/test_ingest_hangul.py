"""한글(.hwp·.hwpx) 읽기 시험 (#24 할 일 1번).

구성: (a) 엔진 독립 자료형으로 만든 가짜 문서로 읽는 규칙 시험(원문 없이 돌아감),
(b) 예비 경로(`rhwp dump`) 인자 모양 시험, (c) 비공개 원문이 있을 때만 도는 회귀 시험.

제안(#24 선진행): (c)를 「원문 파일이 없으면 skip」으로 두는 방식은 팀이 정한 것이 아니라 제안이다.
원문은 비공개라 저장소에 넣지 않으므로, 환경변수 `SPECTON_HANGUL_SAMPLES`가 가리키는 폴더에
두 파일이 있을 때만 돌고, 지정하지 않았거나 파일이 없으면 건너뛴다. 시험 데이터에는 원문 글을 길게
복사하지 않고 숫자·고유번호·문단 번호만 고정한다.
"""

import os
import stat
from pathlib import Path
from typing import Any, NoReturn

import pytest

from specton.contracts.base import ExtractionStatus
from specton.ingest import hangul
from specton.ingest.hangul import (
    NOTICE_BROKEN_MERGE,
    NOTICE_LIST_ONLY,
    NOTICE_PICTURE,
    read_hangul,
)
from specton.ingest.hangul_engine import (
    EngineError,
    HangulCell,
    HangulDocument,
    HangulFormatError,
    HangulTable,
    _cell_text_and_picture,
    dump_paragraph_text,
    read_blocks,
)
from specton.ingest.tabular import (
    NOTICE_DUPLICATE,
    NOTICE_EMPTY,
    NOTICE_NAME_ONLY,
    NOTICE_NO_ID,
    TabularResult,
    UnsupportedInput,
)

_KITECH = "kitech_과업지시서.hwp"
_GYEONGNAM = "경남로봇랜드_붙임3_과업지시서.hwp"

# 가짜 칸 표기: (행, 열, 행병합, 열병합, 글[, 그림 포함])
Spec = tuple[int, int, int, int, str] | tuple[int, int, int, int, str, bool]


def _table(para: int, cells: list[Spec], *, section: int = 0) -> HangulTable:
    made = tuple(HangulCell(*c) for c in cells)
    rows = max(c.row + c.row_span for c in made)
    cols = max(c.col + c.col_span for c in made)
    return HangulTable(section, para, rows, cols, made)


def _kitech_detail(
    para: int, sid: str, definition: str = "정의 글", detail: str = "세부 글", name: str = "명칭"
) -> HangulTable:
    """KITECH 모양 상세표: 5행 3열, 라벨 2칸 병합 + 값 칸."""
    return _table(
        para,
        [
            (0, 0, 1, 2, "요구사항 분류"),
            (0, 2, 1, 1, "기능 요구사항"),
            (1, 0, 1, 2, "요구사항 고유번호"),
            (1, 2, 1, 1, sid),
            (2, 0, 1, 2, "요구사항 명칭"),
            (2, 2, 1, 1, name),
            (3, 0, 2, 1, "요구사항"),
            (3, 1, 1, 1, "정의"),
            (3, 2, 1, 1, definition),
            (4, 1, 1, 1, "세부내용"),
            (4, 2, 1, 1, detail),
        ],
    )


def _gyeongnam_detail(para: int, sid: str, level: str = "필수") -> HangulTable:
    """경남로봇랜드 모양 상세표: 5행 5열, 한 행에 라벨·값 쌍이 둘(고유번호 + 응락수준)."""
    return _table(
        para,
        [
            (0, 0, 1, 2, "요구사항 분류"),
            (0, 2, 1, 3, "기능 요구사항"),
            (1, 0, 1, 2, "요구사항 고유번호"),
            (1, 2, 1, 1, sid),
            (1, 3, 1, 1, "응락수준"),
            (1, 4, 1, 1, level),
            (2, 0, 1, 2, "요구사항 명칭"),
            (2, 2, 1, 3, "명칭"),
            (3, 0, 2, 1, "요구\n사항\n상세\n설명"),
            (3, 1, 1, 1, "정의"),
            (3, 2, 1, 3, "정의 글"),
            (4, 1, 1, 1, "세부\n내용"),
            (4, 2, 1, 3, "세부 글"),
        ],
    )


def _list_table(para: int, rows: list[tuple[str, str]]) -> HangulTable:
    """목록표: 머리 행에 「고유번호」「요구사항명」, 아래 행마다 1건 (KITECH 모양 4열)."""
    cells: list[Spec] = [
        (0, 0, 1, 1, "구분"),
        (0, 1, 1, 1, "고유번호"),
        (0, 2, 1, 1, "요구사항명"),
        (0, 3, 1, 1, "비고"),
    ]
    for i, (sid, name) in enumerate(rows, start=1):
        cells += [(i, 1, 1, 1, sid), (i, 2, 1, 1, name)]
    return _table(para, cells)


def _list_with_head(
    para: int, head: tuple[str, str, str], rows: list[tuple[str, str]]
) -> HangulTable:
    """머리 이름을 고를 수 있는 3열 목록표: (구분, 번호류, 이름) 머리 + 행마다 1건."""
    cells: list[Spec] = [(0, 0, 1, 1, head[0]), (0, 1, 1, 1, head[1]), (0, 2, 1, 1, head[2])]
    for i, (sid, name) in enumerate(rows, start=1):
        cells += [(i, 1, 1, 1, sid), (i, 2, 1, 1, name)]
    return _table(para, cells)


def _read(monkeypatch: pytest.MonkeyPatch, *tables: HangulTable) -> TabularResult:
    """가짜 표들로 `read_hangul`을 돌린다(엔진 대신 자료형을 넣는다)."""
    monkeypatch.setattr(hangul, "read_blocks", lambda path: HangulDocument(tuple(tables)))
    return read_hangul(Path("가짜.hwpx"), "doc-1")


class TestRules:
    def test_kitech_shape_reads_pair_and_location(self, monkeypatch: pytest.MonkeyPatch) -> None:
        [req] = _read(monkeypatch, _kitech_detail(359, "SFR-003")).requirements

        assert req.source_id == "SFR-003"
        assert req.block_id == "SFR-003"  # 원문 고유번호가 있으면 block_id도 그것
        assert req.source_text == "정의 글\n세부 글"  # 정의 → 세부내용, 위에서 아래로 줄바꿈
        assert req.source_extra == {"요구사항 분류": "기능 요구사항", "요구사항 명칭": "명칭"}
        assert req.extraction_status is ExtractionStatus.PASS
        assert req.notice is None
        ref = req.source_ref
        assert (ref.file_format, ref.section, ref.paragraph, ref.table) == ("hwpx", 0, 359, 0)
        assert ref.cell == "C2"  # 고유번호 값 칸: 행 1(→2), 열 2(→C)
        assert ref.page is None  # 쪽 번호는 넣지 않는다

    def test_two_pairs_in_one_row_keep_right_neighbour_rule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """한 행에 라벨·값 쌍이 둘(경남 모양)이어도 각 라벨의 오른쪽 칸이 값이다."""
        [req] = _read(monkeypatch, _gyeongnam_detail(217, "SFR-001", "핵심")).requirements

        assert req.source_id == "SFR-001"  # 「응락수준」 칸이 아니라 바로 오른쪽 칸이 고유번호 값
        assert req.source_acceptance_level == "핵심"
        assert (
            req.source_text == "정의 글\n세부 글"
        )  # 「요구 사항 상세 설명」 묶음 칸은 라벨이 아님
        assert req.source_ref.cell == "C2"

    def test_detail_table_with_attached_requirement_number_label(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """aT 비축 모양: 라벨 「요구사항번호」(붙여 씀)·「요구사항 명칭」·「정의」·「세부 내용」."""
        table = _table(
            236,
            [
                (0, 0, 1, 1, "분류"),
                (0, 1, 1, 2, "기능"),
                (1, 0, 1, 1, "요구사항번호"),
                (1, 1, 1, 2, "SFR-001"),
                (2, 0, 1, 1, "요구사항 명칭"),
                (2, 1, 1, 2, "명칭"),
                (3, 0, 2, 1, "요구사항 상세설명"),
                (3, 1, 1, 1, "정의"),
                (3, 2, 1, 1, "정의 글"),
                (4, 1, 1, 1, "세부 내용"),
                (4, 2, 1, 1, "세부 글"),
            ],
        )
        [req] = _read(monkeypatch, table).requirements
        assert req.source_id == "SFR-001"
        assert req.source_text == "정의 글\n세부 글"
        assert req.extraction_status is ExtractionStatus.PASS
        assert (req.source_ref.paragraph, req.source_ref.cell) == (236, "B2")

    def test_pair_order_in_row_does_not_matter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """응락수준 쌍이 고유번호 쌍보다 왼쪽에 있어도 짝이 바뀌지 않는다."""
        table = _table(
            10,
            [
                (0, 0, 1, 1, "응락수준"),
                (0, 1, 1, 1, "필수"),
                (0, 2, 1, 1, "요구사항 고유번호"),
                (0, 3, 1, 1, "SIR-009"),
                (1, 0, 1, 1, "정의"),
                (1, 1, 1, 3, "정의 글"),
            ],
        )
        [req] = _read(monkeypatch, table).requirements
        assert (req.source_id, req.source_acceptance_level) == ("SIR-009", "필수")
        assert req.source_ref.cell == "D1"

    def test_detail_wins_over_list_and_list_only_is_review(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        list_table = _list_table(5, [("SFR-001", "첫째"), ("SFR-002", "둘째")])
        result = _read(monkeypatch, list_table, _kitech_detail(9, "SFR-001"))

        by_id = {r.source_id: r for r in result.requirements}
        assert len(result.requirements) == 2  # SFR-001은 상세표 1건만
        assert by_id["SFR-001"].source_text == "정의 글\n세부 글"
        assert by_id["SFR-001"].extraction_status is ExtractionStatus.PASS
        only = by_id["SFR-002"]
        assert only.extraction_status is ExtractionStatus.REVIEW
        assert only.source_text == "둘째"  # 이름만으로 낸다
        assert only.notice == NOTICE_LIST_ONLY
        assert (only.source_ref.paragraph, only.source_ref.table, only.source_ref.cell) == (
            5,
            0,
            "B3",
        )

    @pytest.mark.parametrize(
        "head",
        [
            ("구 분", "번 호", "요구사항명"),  # 자치인재원 모양
            ("구분", "ID", "요구사항명"),
            ("요구사항 구분", "Id", "요구사항 명칭"),  # 부록 예시 모양(대소문자 무시)
            ("구분", "요구사항 ID", "요구사항명"),
            ("구분", "요구사항 번호", "요구사항명"),
        ],
    )
    def test_list_header_variants_keep_list_only_ids(
        self, monkeypatch: pytest.MonkeyPatch, head: tuple[str, str, str]
    ) -> None:
        """머리가 「번호」「ID」 등인 목록표도 인식해, 상세표에 없는 번호를 review로 남긴다."""
        list_table = _list_with_head(
            119, head, [("SFR-01", "첫째"), ("SFR-02", "둘째"), ("COR-09", "셋째")]
        )
        result = _read(
            monkeypatch, list_table, _kitech_detail(130, "SFR-01"), _kitech_detail(131, "SFR-02")
        )
        by_id = {r.source_id: r for r in result.requirements}
        assert sorted(by_id) == ["COR-09", "SFR-01", "SFR-02"]
        assert len(result.requirements) == 3  # 상세표 번호는 상세표만(중복 없음)
        assert by_id["SFR-01"].notice is None and by_id["SFR-02"].notice is None
        only = by_id["COR-09"]
        assert only.extraction_status is ExtractionStatus.REVIEW
        assert only.notice == NOTICE_LIST_ONLY
        assert only.source_text == "셋째"
        assert only.source_ref.paragraph == 119

    def test_ellipsis_rows_in_list_are_skipped_but_named_ones_stay(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """번호가 「...」이고 이름이 빈 행은 블록이 없고, 이름이 있으면 review로 남는다."""
        list_table = _list_with_head(
            5, ("구분", "ID", "요구사항명"), [("SFR-01", "첫째"), ("...", ""), ("..", "이름 있음")]
        )
        result = _read(monkeypatch, list_table, _kitech_detail(9, "SFR-02"))
        by_id = {r.source_id: r for r in result.requirements}
        assert sorted(by_id) == ["..", "SFR-01", "SFR-02"]  # 「...」 행만 빠짐
        assert by_id[".."].extraction_status is ExtractionStatus.REVIEW
        assert by_id[".."].source_text == "이름 있음"

    def test_number_label_without_number_values_is_not_a_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """「번호」「요구사항명」 라벨만 있고 아래에 번호꼴 값이 없으면 목록표가 아니다."""
        lookalike = _list_with_head(5, ("구분", "번호", "요구사항명"), [("(없음)", "이름")])
        result = _read(monkeypatch, lookalike, _kitech_detail(9, "SFR-01"))
        assert [r.source_id for r in result.requirements] == ["SFR-01"]

    def test_table_index_counts_in_section_document_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        other_section = _table(1, [(0, 0, 1, 1, "아무 표"), (0, 1, 1, 1, "값")], section=1)
        late = _kitech_detail(7, "SFR-009")
        late = HangulTable(1, late.paragraph, late.rows, late.cols, late.cells)
        result = _read(
            monkeypatch,
            _kitech_detail(3, "SFR-001"),
            _table(4, [(0, 0, 1, 1, "아무 표")]),
            _kitech_detail(5, "SFR-002"),
            other_section,
            late,
        )
        refs = {
            r.source_id: (r.source_ref.section, r.source_ref.table) for r in result.requirements
        }
        assert refs == {"SFR-001": (0, 0), "SFR-002": (0, 2), "SFR-009": (1, 1)}

    def test_empty_definition_falls_back_to_name_and_review(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        [req] = _read(monkeypatch, _kitech_detail(3, "SFR-001", "", "", "이름만")).requirements
        assert req.extraction_status is ExtractionStatus.REVIEW
        assert req.source_text == "이름만"
        assert req.notice == NOTICE_NAME_ONLY

    def test_nothing_to_read_has_no_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        [req] = _read(monkeypatch, _kitech_detail(3, "SFR-001", "", "", "")).requirements
        assert req.extraction_status is ExtractionStatus.REVIEW
        assert req.source_text is None
        assert req.notice == NOTICE_EMPTY

    def test_duplicate_ids_are_all_review_with_distinct_block_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _read(monkeypatch, _kitech_detail(3, "SFR-001"), _kitech_detail(9, "SFR-001"))
        assert [r.extraction_status for r in result.requirements] == [ExtractionStatus.REVIEW] * 2
        assert all(NOTICE_DUPLICATE in (r.notice or "") for r in result.requirements)
        assert [r.block_id for r in result.requirements] == ["S0-P3", "S0-P9"]
        assert {r.source_id for r in result.requirements} == {"SFR-001"}  # 원문 ID는 그대로

    def test_missing_id_value_uses_location_block_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        [req] = _read(monkeypatch, _kitech_detail(42, "")).requirements
        assert req.source_id is None
        assert req.block_id == "S0-P42"  # S{구역}-P{문단}
        assert req.extraction_status is ExtractionStatus.REVIEW
        assert NOTICE_NO_ID in (req.notice or "")

    def test_picture_in_cell_is_review(self, monkeypatch: pytest.MonkeyPatch) -> None:
        table = _kitech_detail(3, "SFR-001")
        cells = (*table.cells[:-1], HangulCell(4, 2, 1, 1, "세부 글", True))
        table = HangulTable(0, 3, table.rows, table.cols, cells)
        [req] = _read(monkeypatch, table).requirements
        assert req.extraction_status is ExtractionStatus.REVIEW
        assert NOTICE_PICTURE in (req.notice or "")
        assert req.source_text == "정의 글\n세부 글"  # 읽은 글은 그대로 둔다

    def test_broken_merge_loses_value_cell_and_is_review(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """「세부내용」 라벨 오른쪽 칸이 없는(병합이 깨진) 표는 조용히 pass가 되지 않는다."""
        table = _kitech_detail(3, "SFR-001")
        cells = tuple(c for c in table.cells if not (c.row == 4 and c.col == 2))
        table = HangulTable(0, 3, table.rows, table.cols, cells)
        [req] = _read(monkeypatch, table).requirements
        assert req.extraction_status is ExtractionStatus.REVIEW
        assert NOTICE_BROKEN_MERGE in (req.notice or "")

    def test_no_requirement_table_stops_the_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(UnsupportedInput) as info:
            _read(monkeypatch, _table(3, [(0, 0, 1, 1, "목차"), (0, 1, 1, 1, "1")]))
        assert info.value.notice and info.value.detail

    def test_list_table_only_stops_the_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """목록표만 있고 상세표가 0개면 review 블록으로 때우지 않고 파일 단위로 멈춘다."""
        with pytest.raises(UnsupportedInput):
            _read(monkeypatch, _list_table(5, [("SFR-001", "첫째")]))

    def test_no_tables_stops_the_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(UnsupportedInput):
            _read(monkeypatch)

    def test_engine_format_error_becomes_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(path: Path) -> None:
            raise HangulFormatError("깨짐")

        monkeypatch.setattr(hangul, "read_blocks", boom)
        with pytest.raises(UnsupportedInput, match="열 수 없어요"):
            read_hangul(Path("x.hwp"), "doc-1")

    def test_engine_error_becomes_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def boom(path: Path) -> None:
            raise EngineError("연결부")

        monkeypatch.setattr(hangul, "read_blocks", boom)
        with pytest.raises(UnsupportedInput, match="도중 문제"):
            read_hangul(Path("x.hwp"), "doc-1")

    def test_real_engine_rejects_garbage_file(self, tmp_path: Path) -> None:
        """깨진 파일은 실제 엔진을 거쳐도 빈 결과가 아니라 UnsupportedInput이다."""
        for name in ("a.hwp", "b.hwpx"):
            path = tmp_path / name
            path.write_bytes(b"not a hangul file" * 20)
            with pytest.raises(UnsupportedInput):
                read_hangul(path, "doc-1")
        empty = tmp_path / "empty.hwp"
        empty.write_bytes(b"")
        with pytest.raises(UnsupportedInput):
            read_hangul(empty, "doc-1")

    def test_file_access_error_has_its_own_notice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """권한 오류는 엔진 연결 오류가 아니라 파일 접근 안내로 멈춘다."""

        def boom(path: Path) -> None:
            raise PermissionError(13, "denied")

        monkeypatch.setattr(hangul, "read_blocks", boom)
        with pytest.raises(UnsupportedInput) as info:
            read_hangul(Path("x.hwp"), "doc-1")
        assert "파일 권한이나 경로" in info.value.notice
        assert "PermissionError" in info.value.detail
        assert "엔진" not in info.value.detail

    def test_directory_path_is_file_access_error(self, tmp_path: Path) -> None:
        """폴더를 파일로 준 경우도(실제 엔진 경유) 연결 오류가 아닌 접근 안내다."""
        _require_engine()
        with pytest.raises(UnsupportedInput) as info:
            read_hangul(tmp_path, "doc-1")
        assert "파일 권한이나 경로" in info.value.notice
        assert "엔진" not in info.value.detail

    def test_id_value_cell_vanished_by_merge(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """고유번호 값 칸이 병합으로 사라진 표: 파일이 멈추지 않고 review 블록이 된다."""
        table = _kitech_detail(8, "SFR-001")
        cells = tuple(c for c in table.cells if not (c.row == 1 and c.col == 2))
        table = HangulTable(0, 8, table.rows, table.cols, cells)
        result = _read(monkeypatch, _kitech_detail(3, "SFR-002"), table)
        broken = next(r for r in result.requirements if r.source_id is None)
        assert broken.extraction_status is ExtractionStatus.REVIEW
        assert broken.block_id == "S0-P8"
        assert NOTICE_NO_ID in (broken.notice or "")
        assert NOTICE_BROKEN_MERGE in (broken.notice or "")
        # 위치 칸은 값 칸이 없어 표의 첫 칸(A1)으로 대신한다
        assert broken.source_ref.cell == "A1"
        assert len(result.requirements) == 2

    def test_missing_file_is_not_hidden(self, tmp_path: Path) -> None:
        _require_engine()
        with pytest.raises(FileNotFoundError):
            read_hangul(tmp_path / "없음.hwp", "doc-1")

    def test_related_requirements_cell_is_kept_as_written(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """상세표의 「관련 요구사항」 칸 값은 엑셀 읽기처럼 원문 글 그대로 담는다."""
        base = _kitech_detail(359, "SFR-003")
        table = _table(
            359,
            [
                *((c.row, c.col, c.row_span, c.col_span, c.text) for c in base.cells),
                (5, 0, 1, 2, "관련 요구사항"),
                (5, 2, 1, 1, "SFR-002, SFR-001, DAR-001"),
            ],
        )

        [req] = _read(monkeypatch, table).requirements

        assert req.source_related_requirements == "SFR-002, SFR-001, DAR-001"
        assert req.extraction_status is ExtractionStatus.PASS  # 새 라벨이 판정을 바꾸지 않음
        assert (
            "관련 요구사항" not in req.source_extra
        )  # 별도 칸이라 source_extra에 중복해 넣지 않음

    def test_empty_or_missing_related_requirements_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """값 칸이 비어 있거나 라벨이 없으면 None이다(엑셀 읽기의 빈 칸과 같음)."""
        base = _kitech_detail(359, "SFR-001")
        empty = _table(
            359,
            [
                *((c.row, c.col, c.row_span, c.col_span, c.text) for c in base.cells),
                (5, 0, 1, 2, "관련 요구사항"),
                (5, 2, 1, 1, ""),
            ],
        )

        [with_empty] = _read(monkeypatch, empty).requirements
        [without_label] = _read(monkeypatch, base).requirements

        assert with_empty.source_related_requirements is None
        assert without_label.source_related_requirements is None

    def test_related_label_next_to_output_label_is_not_taken_as_its_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """「산출정보」 오른쪽이 「관련 요구사항」 라벨이면 그 글자를 값으로 잡지 않는다."""
        base = _kitech_detail(359, "SFR-004")
        table = _table(
            359,
            [
                *((c.row, c.col, c.row_span, c.col_span, c.text) for c in base.cells),
                (5, 0, 1, 1, "산출정보"),
                (5, 1, 1, 1, "관련 요구사항"),
                (5, 2, 1, 1, "SFR-003, SFR-001"),
            ],
        )

        [req] = _read(monkeypatch, table).requirements

        assert "산출정보" not in req.source_extra  # 라벨 글자가 값으로 들어가지 않음
        assert req.source_related_requirements == "SFR-003, SFR-001"


class TestFallbackDump:
    def _fake_rhwp(self, directory: Path, *, exit_code: int = 0) -> Path:
        log = directory / "args.txt"
        script = directory / "rhwp"
        script.write_text(
            f'#!/bin/sh\nprintf "%s\\n" "$@" > "{log}"\necho 가짜출력\nexit {exit_code}\n',
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return log

    def test_command_shape_and_raw_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        log = self._fake_rhwp(tmp_path)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")

        out = dump_paragraph_text(Path("문서.hwp"), 2, 45)

        # 명령 인자 모양만 확인한다(출력 형식은 미확인이라 가공하지 않고 그대로 돌려준다)
        assert log.read_text(encoding="utf-8").split() == [
            "dump",
            "-s",
            "2",
            "-p",
            "45",
            "문서.hwp",
        ]
        assert out == "가짜출력\n"

    def test_missing_executable_is_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("PATH", str(tmp_path))  # rhwp가 없는 빈 폴더만
        with pytest.raises(EngineError, match="rhwp 실행파일"):
            dump_paragraph_text(Path("문서.hwp"), 0, 0)

    def test_failure_exit_code_is_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._fake_rhwp(tmp_path, exit_code=3)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
        with pytest.raises(EngineError, match="종료 코드 3"):
            dump_paragraph_text(Path("문서.hwp"), 0, 0)


def _is_known_linux_wheel_failure(exc: ImportError) -> bool:
    """리눅스 휠의 알려진 import 실패(`FT_Palette_Data_Get`, 상류 #31)인가."""
    return "FT_Palette_Data_Get" in str(exc)


def _skip_or_raise_engine_import_error(exc: ImportError) -> NoReturn:
    """엔진 import 실패를 어떻게 다룰지 정한다.

    리눅스에서 rhwp-python 0.8.1 휠은 시스템 FreeType 선로드(LD_PRELOAD)가 없으면
    `undefined symbol: FT_Palette_Data_Get`로 import가 실패한다(상류 DanMeon/rhwp-python #31).
    이 알려진 오류만 건너뛰고, 그 밖의 import 실패(의존성 누락·휠 손상)는 그대로 올려
    시험이 실패하게 한다. 환경변수 `SPECTON_REQUIRE_ENGINE`이 정확히 "1"이면(true·yes는 무시)
    알려진 오류도 실패로 둔다(선로드 단계를 넣은 CI용).
    """
    if _is_known_linux_wheel_failure(exc) and os.environ.get("SPECTON_REQUIRE_ENGINE") != "1":
        pytest.skip(f"rhwp를 불러올 수 없어 건너뜀(상류 #31): {exc}")
    raise exc


def _import_engine() -> Any:
    """진짜 rhwp 엔진이 필요한 시험이 엔진을 불러온다. 알려진 휠 오류면 건너뛴다."""
    try:
        import rhwp
    except ImportError as exc:
        _skip_or_raise_engine_import_error(exc)
    return rhwp


def _require_engine() -> None:
    _import_engine()


def _samples() -> Path:
    given = os.environ.get("SPECTON_HANGUL_SAMPLES")
    folder = Path(given) if given else None
    if folder is None or not (folder / _KITECH).exists() or not (folder / _GYEONGNAM).exists():
        pytest.skip(
            "비공개 한글 원문이 없어 건너뜀. 환경변수 SPECTON_HANGUL_SAMPLES를 지정하면 돌아간다"
        )
    return folder


def _key_map(path: Path) -> dict[str, tuple[int | None, int | None, int | None, str | None]]:
    result = read_hangul(path, "doc")
    return {
        r.source_id or r.block_id: (
            r.source_ref.section,
            r.source_ref.paragraph,
            r.source_ref.table,
            r.source_ref.cell,
        )
        for r in result.requirements
    }


class TestRegressionOnRealFiles:
    def test_kitech(self) -> None:
        _require_engine()
        result = read_hangul(_samples() / _KITECH, "kitech")
        reqs = result.requirements
        detail = [r for r in reqs if r.notice != NOTICE_LIST_ONLY]
        list_only = [r for r in reqs if r.notice == NOTICE_LIST_ONLY]

        sfr = sorted(r.source_id or "" for r in reqs if (r.source_id or "").startswith("SFR-"))
        assert sfr == [f"SFR-{n:03d}" for n in range(1, 13)]
        # 원문 고유번호 41개(목록표) 중 상세표에서 뽑은 것 40개, 목록표만 1개(TER-005)
        assert (len(reqs), len(detail), len(list_only)) == (41, 40, 1)
        assert [r.source_id for r in list_only] == ["TER-005"]
        assert (list_only[0].source_ref.paragraph, list_only[0].source_ref.table) == (347, 6)
        sfr3 = next(r for r in reqs if r.source_id == "SFR-003")
        assert (sfr3.source_ref.section, sfr3.source_ref.paragraph) == (0, 359)
        assert sfr3.source_ref.page is None
        assert all(r.extraction_status is ExtractionStatus.PASS for r in detail)

    def test_gyeongnam(self) -> None:
        _require_engine()
        reqs = read_hangul(_samples() / _GYEONGNAM, "gyeongnam").requirements
        sfr = sorted(r.source_id or "" for r in reqs if (r.source_id or "").startswith("SFR-"))
        assert sfr == [f"SFR-{n:03d}" for n in range(1, 23)]
        # 원문 고유번호 64개(목록표) 중 상세표에서 뽑은 것 64개, 목록표만 0개
        assert len(reqs) == 64
        assert all(r.notice is None for r in reqs)
        assert all(r.source_acceptance_level == "필수" for r in reqs)

    def test_hwp_and_exported_hwpx_give_same_locations(self, tmp_path: Path) -> None:
        """.hwp → export_hwpx → 다시 읽기에서 고유번호별 (구역·문단·표 순번·칸)이 같다.

        2026-11-07 실제 실행 결과: 두 원문 모두 같았다(KITECH 41건·경남 64건).
        """
        rhwp = _import_engine()  # 알려진 휠 오류면 건너뜀
        # (시험에서 엔진을 직접 쓰는 것은 허용: 원본을 hwpx로 내보내려는 용도)

        for name in (_KITECH, _GYEONGNAM):
            exported = tmp_path / (Path(name).stem + ".hwpx")
            rhwp.parse(str(_samples() / name)).export_hwpx(str(exported))
            assert _key_map(exported) == _key_map(_samples() / name)


class ParagraphBlock:
    """엔진 객체 모양 흉내: 클래스 이름이 엔진 블록 종류와 같아야 한다(type(x).__name__로 구분)."""

    def __init__(self, text: str) -> None:
        self.text = text


class PictureBlock:  # text 속성이 없는 것까지 엔진과 같다
    pass


class _FakeCell:
    def __init__(self, row: int, col: int, *blocks: object) -> None:
        self.row, self.col, self.blocks = row, col, list(blocks)


class TableBlock:
    def __init__(self, cells: list[_FakeCell], text: str = "") -> None:
        self.cells, self.text = cells, text


def test_nested_tables_keep_all_text_two_levels_deep() -> None:
    """칸 안 2단 중첩 표의 글이 모두 칸 글에 들어간다(엔진 `.text`는 안쪽 표를 빠뜨린다)."""
    inner = TableBlock([_FakeCell(0, 0, ParagraphBlock("안쪽 둘째 단"))], text="")
    outer = TableBlock(
        [
            _FakeCell(0, 1, ParagraphBlock("가운데 오른쪽")),
            _FakeCell(0, 0, ParagraphBlock("가운데 왼쪽"), inner),
            _FakeCell(1, 0, ParagraphBlock("")),  # 빈 글은 건너뜀
        ],
        text="엔진이 만든 불완전한 글",
    )
    text, picture = _cell_text_and_picture([ParagraphBlock("칸 첫 문단"), outer])
    assert text == "칸 첫 문단\n가운데 왼쪽\n안쪽 둘째 단\n가운데 오른쪽"
    assert picture is False


def test_picture_inside_nested_table_sets_flag() -> None:
    inner = TableBlock([_FakeCell(0, 0, PictureBlock())])
    outer = TableBlock([_FakeCell(0, 0, inner)])
    assert _cell_text_and_picture([outer]) == ("", True)


def test_read_blocks_is_the_only_engine_door() -> None:
    """저장소에서 rhwp를 직접 가져오는 곳은 hangul_engine.py 하나뿐이다.

    시험 파일은 검사 대상이 아니다(`specton/`만 훑는다). 시험이 엔진을 직접 가져오는 곳은 원본을
    hwpx로 내보내는 회귀 시험과 아래 엔진 이름 확인 시험, 두 군데다.
    """
    root = Path(__file__).resolve().parents[2]
    users = [
        p.relative_to(root).as_posix()
        for p in (root / "specton").rglob("*.py")
        if "import rhwp" in p.read_text(encoding="utf-8")
        or "from rhwp" in p.read_text(encoding="utf-8")
    ]
    assert users == ["specton/ingest/hangul_engine.py"]
    assert read_blocks  # 공개 함수 존재 확인


_UPGRADE_HINT = (
    "rhwp-python 버전을 올릴 때는 비공개 원문 회귀를 로컬에서 먼저 돌릴 것"
    "(SPECTON_HANGUL_SAMPLES 지정). "
    "hangul_engine.py가 문자열로 비교하는 엔진 이름이 바뀌면 조용히 깨진다"
)


def test_engine_block_names_still_exist_in_rhwp() -> None:
    """hangul_engine이 클래스 이름 문자열로 비교하는 엔진 블록이 실제 엔진에 아직 있는가.

    이유: 코드는 `type(block).__name__ == "TableBlock"`처럼 이름 글자로 구분한다(엔진 클래스를
    직접 import하면 엔진 의존이 여러 곳으로 퍼진다). 엔진이 이름을 바꾸면 에러 없이 표가 사라지므로,
    버전을 올릴 때 CI가 잡도록 원문 없이 돌아가는 이 시험을 둔다. 이 시험 안에서만 rhwp를 직접 쓴다.
    """
    import re

    # 알려진 리눅스 휠 오류면 건너뛰고, 그 밖의 import 실패는 시험 실패로 둔다
    _require_engine()
    from rhwp.ir import nodes  # 시험에서 엔진 직접 사용 허용(위 이유)

    source = (
        Path(__file__).resolve().parents[2] / "specton" / "ingest" / "hangul_engine.py"
    ).read_text(encoding="utf-8")
    names = set(re.findall(r'"(\w+Block)"', source))  # 코드에서 직접 뽑는다
    assert {"TableBlock", "PictureBlock", "FieldBlock"} <= names
    # 문단은 이름 비교 없이 「그 밖의 블록」으로 읽지만 text·prov 필드를 쓰므로 함께 확인한다
    names.add("ParagraphBlock")

    for name in sorted(names):
        assert hasattr(nodes, name), f"엔진에 {name} 클래스가 없음. {_UPGRADE_HINT}"

    def fields(cls_name: str) -> set[str]:
        return set(getattr(nodes, cls_name).model_fields)

    need = {
        "TableBlock": {"cells", "rows", "cols", "prov", "text"},
        "ParagraphBlock": {"text", "prov"},
        "TableCell": {"row", "col", "row_span", "col_span", "blocks"},
    }
    for cls_name, wanted in need.items():
        missing = wanted - fields(cls_name)
        assert not missing, f"{cls_name}에 필드 {sorted(missing)}가 없음. {_UPGRADE_HINT}"
    prov_missing = {"section_idx", "para_idx"} - fields("Provenance")
    assert not prov_missing, f"Provenance에 필드 {sorted(prov_missing)}가 없음. {_UPGRADE_HINT}"


class TestEngineImportGuard:
    """엔진을 못 불러올 때 어떤 경우만 건너뛰는지 확인한다(CI가 엔진 회귀를 조용히 덮지 않게).

    이유: 리눅스 휠의 알려진 오류(`FT_Palette_Data_Get`, 상류 #31)만 건너뛰고, 그 밖의 import 실패
    (의존성 누락·휠 손상)는 시험 실패로 드러나야 한다.
    `SPECTON_REQUIRE_ENGINE=1`이면 알려진 오류도 실패다.
    """

    _KNOWN = ImportError("…/_rhwp.abi3.so: undefined symbol: FT_Palette_Data_Get")

    def test_known_wheel_failure_skips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPECTON_REQUIRE_ENGINE", raising=False)
        with pytest.raises(pytest.skip.Exception):
            _skip_or_raise_engine_import_error(self._KNOWN)

    def test_other_import_error_is_not_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPECTON_REQUIRE_ENGINE", raising=False)
        with pytest.raises(ImportError, match="No module named"):
            _skip_or_raise_engine_import_error(ModuleNotFoundError("No module named 'rhwp'"))

    def test_require_engine_env_turns_skip_into_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SPECTON_REQUIRE_ENGINE", "1")
        with pytest.raises(ImportError, match="FT_Palette_Data_Get"):
            _skip_or_raise_engine_import_error(self._KNOWN)


def test_installed_engine_version_matches_pin() -> None:
    """설치된 rhwp-python 버전이 pyproject.toml의 고정 버전과 같다.

    엔진을 import하지 않으므로 엔진을 못 불러오는 환경에서도 항상 돈다.
    """
    import re
    from importlib.metadata import version

    pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    pinned = re.search(r'"rhwp-python==([\w.]+)"', pyproject)
    assert pinned, "pyproject.toml에서 rhwp-python 고정 버전을 찾지 못함"
    assert version("rhwp-python") == pinned.group(1), (
        "설치된 버전이 핀과 다름. `uv sync --locked`로 다시 설치"
    )
