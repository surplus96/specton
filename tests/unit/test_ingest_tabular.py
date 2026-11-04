from pathlib import Path

import pytest
from openpyxl import Workbook

from specton.contracts.base import ExtractionStatus
from specton.ingest.tabular import UnsupportedInput, read_csv, read_excel

HEADER = ["요구사항 ID", "구분", "요구사항명", "상세 내용", "출처", "관련 요구사항"]


def _xlsx(path: Path, rows: list[list[object]], *, title_rows: int = 0) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "요구사항"
    for i in range(title_rows):
        sheet.append([f"제목 {i}"])
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


class TestExcel:
    def test_reads_rows_with_location(self, tmp_path: Path) -> None:
        path = _xlsx(
            tmp_path / "a.xlsx",
            [HEADER, ["INV-001", "기능", "입고 등록", "입고를 등록한다", "RFP 3장", "INV-002"]],
            title_rows=1,
        )
        result = read_excel(path, "doc-1")

        [req] = result.requirements
        assert req.source_id == "INV-001"
        assert req.source_text == "입고를 등록한다"
        assert req.source_ref.sheet == "요구사항"
        assert req.source_ref.row == 3  # 제목 1행 + 머리글 1행 다음
        assert req.source_related_requirements == "INV-002"
        assert req.source_extra == {"구분": "기능", "요구사항명": "입고 등록", "출처": "RFP 3장"}
        assert req.extraction_status is ExtractionStatus.PASS

    def test_two_row_header_is_combined(self, tmp_path: Path) -> None:
        path = _xlsx(
            tmp_path / "b.xlsx",
            [
                ["요구사항", "요구사항", "상세"],
                ["ID", "명칭", "내용"],
                ["INV-001", "입고 등록", "입고를 등록한다"],
            ],
        )
        [req] = read_excel(path, "doc-1").requirements
        assert req.source_id == "INV-001"
        assert req.source_text == "입고를 등록한다"

    def test_title_row_and_public_two_row_header(self, tmp_path: Path) -> None:
        """공공 양식: 제목 줄 + 「상세설명」 아래 「정의·세부내용」 2단 머리글."""
        from openpyxl import load_workbook

        path = _xlsx(
            tmp_path / "p.xlsx",
            [
                ["요구사항 분류", "요구사항 고유번호", "요구사항 명칭", "요구사항 상세설명", None],
                [None, None, None, "정의", "세부내용"],
                ["기능 요구사항", "SFR-001", "입고 관리", "입고를 관리한다", "① 입고 등록"],
            ],
            title_rows=1,
        )
        book = load_workbook(path)
        sheet = book.active
        for col in "ABC":
            sheet.merge_cells(f"{col}2:{col}3")
        sheet.merge_cells("D2:E2")
        book.save(path)

        [req] = read_excel(path, "doc-1").requirements
        assert req.source_id == "SFR-001"
        assert req.source_ref.row == 4
        # 「정의」와 「세부내용」을 줄바꿈으로 이어 원문 문장으로 쓴다
        assert req.source_text == "입고를 관리한다\n① 입고 등록"
        assert "요구사항 상세설명 세부내용" not in req.source_extra

    def test_header_without_id_column(self, tmp_path: Path) -> None:
        """ID 칸이 없는 양식도 명칭 + 내용이 있으면 읽고, 원문 위치로 잇는다."""
        path = _xlsx(
            tmp_path / "noid.xlsx",
            [["구분", "요구사항명", "상세 설명"], ["이용자", "회원가입", "이메일로 가입한다"]],
        )
        [req] = read_excel(path, "doc-1").requirements
        assert req.source_id is None
        assert req.source_text == "이메일로 가입한다"
        assert req.source_ref.row == 2
        assert req.extraction_status == ExtractionStatus.REVIEW  # ID 없음

    def test_header_id_and_description_only(self, tmp_path: Path) -> None:
        """명칭 칸이 없어도 ID + 내용이면 머리글로 본다."""
        path = _xlsx(
            tmp_path / "idd.xlsx",
            [["요구사항 ID", "요구사항 설명"], ["REQ-01", "로그인한다"]],
        )
        [req] = read_excel(path, "doc-1").requirements
        assert (req.source_id, req.source_text) == ("REQ-01", "로그인한다")

    def test_change_log_sheet_is_not_requirements(self, tmp_path: Path) -> None:
        """「변경ID」·「변경 내용」 같은 변경 이력 표는 요구사항 표로 읽지 않는다 (=ID, =내용)."""
        from openpyxl import load_workbook

        path = _xlsx(tmp_path / "log.xlsx", [HEADER, ["INV-001", "기능", "입고", "입고 등록"]])
        book = load_workbook(path)
        log = book.create_sheet("변경 이력")
        log.append(["변경ID", "대상 요구사항", "변경 내용"])
        log.append(["C-01", "REQ-U-047", "문구 수정"])
        book.save(path)

        result = read_excel(path, "doc-1")
        assert [r.source_id for r in result.requirements] == ["INV-001"]
        assert result.skipped_sheets == ("변경 이력",)

    def test_name_in_parentheses(self, tmp_path: Path) -> None:
        """「소분류(기능설명)」은 본문, 「요구사항(목표)」도 본문으로 맞춘다."""
        path = _xlsx(
            tmp_path / "paren.xlsx",
            [["요구사항ID", "소분류(기능설명)"], ["REQ-01", "로그인한다"]],
        )
        [req] = read_excel(path, "doc-1").requirements
        assert req.source_text == "로그인한다"
        path2 = _xlsx(
            tmp_path / "goal.xlsx", [["요구사항ID", "요구사항(목표)"], ["NFR-01", "3초 안에 응답"]]
        )
        [req2] = read_excel(path2, "doc-1").requirements
        assert req2.source_text == "3초 안에 응답"

    def test_plain_requirement_column(self, tmp_path: Path) -> None:
        """「요구사항」 칸만 있으면 본문, 「요구사항 설명」과 같이 있으면 명칭이다."""
        path = _xlsx(tmp_path / "a.xlsx", [["요구사항 ID", "요구사항"], ["log-01", "로그인 화면"]])
        [req] = read_excel(path, "doc-1").requirements
        assert (req.source_text, req.extraction_status) == ("로그인 화면", ExtractionStatus.PASS)
        path2 = _xlsx(
            tmp_path / "b.xlsx",
            [["요구사항ID", "요구사항", "요구사항 설명"], ["R-1", "로그인", "이메일로 로그인한다"]],
        )
        [req2] = read_excel(path2, "doc-1").requirements
        assert req2.source_text == "이메일로 로그인한다"
        assert req2.source_extra["요구사항"] == "로그인"

    def test_formula_error_value_goes_to_review(self, tmp_path: Path) -> None:
        """#REF! 같은 수식 오류값은 원문이 아니므로 확인 필요로 둔다."""
        path = _xlsx(tmp_path / "err.xlsx", [HEADER, ["INV-001", "기능", "입고", "#REF!"]])
        [req] = read_excel(path, "doc-1").requirements
        assert req.extraction_status == ExtractionStatus.REVIEW

    def test_hidden_row_goes_to_review(self, tmp_path: Path) -> None:
        """작성자가 숨긴 행은 버리지 않고 확인 대상으로 둔다."""
        from openpyxl import load_workbook

        path = _xlsx(
            tmp_path / "h.xlsx",
            [
                HEADER,
                ["INV-001", "기능", "입고", "입고 등록"],
                ["INV-002", "기능", "출고", "출고 등록"],
            ],
        )
        book = load_workbook(path)
        book.active.row_dimensions[3].hidden = True
        book.save(path)

        reqs = read_excel(path, "doc-1").requirements
        assert [r.extraction_status for r in reqs] == [
            ExtractionStatus.PASS,
            ExtractionStatus.REVIEW,
        ]

    def test_vertical_merged_id_groups_rows(self, tmp_path: Path) -> None:
        """ID 칸이 세로 병합된 행들은 요구사항 1건으로 묶는다."""
        from openpyxl import load_workbook

        path = _xlsx(
            tmp_path / "m.xlsx",
            [
                ["고유번호", "요구사항 명칭", "세부 내용", "신규 요구사항ID"],
                ["SFR-001", "포털 구축", "○ 포털 기능", "SFR-001-UP-01"],
                [None, None, None, "SFR-001-UP-02"],
                ["SFR-002", "검색", "○ 검색 기능", "SFR-002-UP-01"],
            ],
        )
        book = load_workbook(path)
        sheet = book.active
        for col in "ABC":
            sheet.merge_cells(f"{col}2:{col}3")
        book.save(path)

        reqs = read_excel(path, "doc-1").requirements
        assert [r.source_id for r in reqs] == ["SFR-001", "SFR-002"]
        assert reqs[0].source_text == "○ 포털 기능"
        assert reqs[0].source_extra["신규 요구사항ID"] == "SFR-001-UP-01\nSFR-001-UP-02"
        assert reqs[0].extraction_status == ExtractionStatus.PASS

    def test_vertical_merge_fills_down(self, tmp_path: Path) -> None:
        path = _xlsx(
            tmp_path / "c.xlsx",
            [
                HEADER,
                ["INV-001", "기능", "입고", "입고 등록"],
                ["INV-002", None, "출고", "출고 등록"],
            ],
        )
        book_path = path
        from openpyxl import load_workbook

        book = load_workbook(book_path)
        book.active.merge_cells("B2:B3")
        book.save(book_path)

        reqs = read_excel(book_path, "doc-1").requirements
        assert [r.source_extra["구분"] for r in reqs] == ["기능", "기능"]

    def test_missing_id_and_duplicate_id_go_to_review(self, tmp_path: Path) -> None:
        path = _xlsx(
            tmp_path / "d.xlsx",
            [
                HEADER,
                [None, "기능", "입고", "입고 등록"],
                ["INV-002", "기능", "출고", "출고 등록"],
                ["INV-002", "기능", "반품", "반품 등록"],
            ],
        )
        reqs = read_excel(path, "doc-1").requirements
        assert [r.extraction_status for r in reqs] == [ExtractionStatus.REVIEW] * 3

    def test_row_without_text_is_reported_not_dropped(self, tmp_path: Path) -> None:
        path = _xlsx(tmp_path / "e.xlsx", [HEADER, ["INV-001", "기능", None, None]])
        result = read_excel(path, "doc-1")
        assert result.requirements == ()
        [issue] = result.issues
        assert issue.source_ref.row == 2
        assert issue.notice and issue.detail

    def test_formula_without_cached_value_goes_to_review(self, tmp_path: Path) -> None:
        path = _xlsx(tmp_path / "f.xlsx", [HEADER, ["INV-001", "기능", "입고", '="입고"&"등록"']])
        [req] = read_excel(path, "doc-1").requirements
        assert req.source_text == "입고"  # 결과값이 없어 요구사항명을 씀
        assert req.extraction_status is ExtractionStatus.REVIEW

    def test_sheet_without_header_is_skipped_and_named(self, tmp_path: Path) -> None:
        path = _xlsx(tmp_path / "g.xlsx", [HEADER, ["INV-001", "기능", "입고", "입고 등록"]])
        from openpyxl import load_workbook

        book = load_workbook(path)
        book.create_sheet("개정이력").append(["버전", "날짜"])
        book.save(path)
        result = read_excel(path, "doc-1")
        assert result.skipped_sheets == ("개정이력",)
        assert len(result.requirements) == 1

    def test_workbook_without_sheets_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """시트가 0개로 열리는 파일(Strict OOXML 등)은 빈 결과 대신 안내한다."""
        import specton.ingest.tabular as tabular

        path = _xlsx(tmp_path / "s.xlsx", [HEADER])
        real = tabular.load_workbook

        def no_sheets(*args: object, **kwargs: object) -> object:
            book = real(*args, **kwargs)
            for sheet in list(book.worksheets):
                book.remove(sheet)
            return book

        monkeypatch.setattr(tabular, "load_workbook", no_sheets)
        with pytest.raises(UnsupportedInput, match="시트를 읽지 못했어요"):
            read_excel(path, "doc-1")

    @pytest.mark.parametrize("content", [b"", b"not a zip", b"PK\x03\x04broken"])
    def test_broken_file_is_rejected(self, tmp_path: Path, content: bytes) -> None:
        """깨진 .xlsx는 서버 오류 대신 다시 저장 안내를 돌려준다."""
        path = tmp_path / "broken.xlsx"
        path.write_bytes(content)
        with pytest.raises(UnsupportedInput, match="파일을 열 수 없어요"):
            read_excel(path, "doc-1")

    def test_no_requirement_table_in_any_sheet_is_rejected(self, tmp_path: Path) -> None:
        """어느 시트에도 요구사항 표가 없으면 0건 대신 안내한다."""
        path = _xlsx(tmp_path / "none.xlsx", [["구분", "필요 기능"], ["회원", "로그인"]])
        with pytest.raises(UnsupportedInput, match="요구사항 표를 찾지 못했어요"):
            read_excel(path, "doc-1")

    def test_template_without_rows_is_rejected_as_empty_form(self, tmp_path: Path) -> None:
        """파일 전체가 머리글만 있는 빈 양식이면 0건으로 넘기지 않고 파일 단위로 안내한다."""
        with pytest.raises(UnsupportedInput) as info:
            read_excel(_xlsx(tmp_path / "t.xlsx", [HEADER]), "doc-1")
        assert info.value.notice.startswith("요구사항이 없는 빈 양식이에요")
        assert "칸 이름만 있고" in info.value.detail

    def test_empty_sheet_next_to_filled_sheet_is_info_only(self, tmp_path: Path) -> None:
        """다른 시트에 요구사항이 있으면 머리글만 있는 시트는 정보(skipped_sheets)로만 알린다."""
        from openpyxl import load_workbook

        path = _xlsx(tmp_path / "two.xlsx", [HEADER, ["INV-001", "기능", "입고", "입고 등록"]])
        book = load_workbook(path)
        book.create_sheet("빈 표").append(HEADER)
        book.save(path)

        result = read_excel(path, "doc-1")
        assert len(result.requirements) == 1
        assert result.issues == ()  # 확인·제외할 원문 줄이 없으므로 확인 필요가 아니다
        assert result.skipped_sheets == ("빈 표",)

    def test_unsupported_input_has_notice_and_detail(self, tmp_path: Path) -> None:
        """안내는 팝업용 짧은 문장(notice)과 「자세히 보기」(detail) 두 칸으로 나뉜다."""
        path = tmp_path / "old.xls"
        path.write_bytes(b"x")
        with pytest.raises(UnsupportedInput) as info:
            read_excel(path, "doc-1")
        assert info.value.notice.startswith("이 형식은 올릴 수 없어요")
        assert "옛 엑셀(.xls)" in info.value.detail

    def test_header_message_shows_found_labels(self, tmp_path: Path) -> None:
        path = _xlsx(
            tmp_path / "e.xlsx", [["구분", "필요 기능", "기능 설명"], ["회원", "로그인", "x"]]
        )
        with pytest.raises(UnsupportedInput, match="찾은 칸 이름: 구분, 필요 기능, 기능 설명"):
            read_excel(path, "doc-1")

    def test_macro_file_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "m.xlsm"
        path.write_bytes(b"")
        with pytest.raises(UnsupportedInput, match="매크로"):
            read_excel(path, "doc-1")


class TestCsv:
    def test_cp949_and_semicolon(self, tmp_path: Path) -> None:
        path = tmp_path / "a.csv"
        path.write_bytes(
            "요구사항 ID;요구사항명;상세 내용\nINV-001;입고;입고 등록\n".encode("cp949")
        )
        [req] = read_csv(path, "doc-1").requirements
        assert req.source_id == "INV-001"
        assert req.source_ref.file_format == "csv"
        assert req.source_ref.row == 2

    def test_utf8_with_bom(self, tmp_path: Path) -> None:
        path = tmp_path / "b.csv"
        path.write_text(
            "요구사항 ID,요구사항명,상세 내용\nINV-001,입고,입고 등록\n", encoding="utf-8-sig"
        )
        [req] = read_csv(path, "doc-1").requirements
        assert req.source_id == "INV-001"

    def test_missing_id_duplicate_id_and_empty_text(self, tmp_path: Path) -> None:
        """TC-F01 CSV: ID 없음·중복 ID는 확인 대상, 원문이 빈 행은 확인 필요로 남긴다."""
        path = tmp_path / "d.csv"
        path.write_text(
            "요구사항 ID,요구사항명,상세 내용\n"
            ",입고,입고 등록\nINV-002,출고,출고 등록\nINV-002,반품,반품 등록\nINV-004,,\n",
            encoding="utf-8",
        )
        result = read_csv(path, "doc-1")
        assert [r.extraction_status for r in result.requirements] == [ExtractionStatus.REVIEW] * 3
        [issue] = result.issues
        assert issue.source_ref.row == 5

    def test_header_without_id_column(self, tmp_path: Path) -> None:
        path = tmp_path / "e.csv"
        path.write_text("요구사항명,상세 설명\n회원가입,이메일로 가입한다\n", encoding="utf-8")
        [req] = read_csv(path, "doc-1").requirements
        assert (req.source_id, req.source_text) == (None, "이메일로 가입한다")

    def test_undecodable_csv_reports_the_line(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.csv"
        path.write_bytes(
            "요구사항 ID,요구사항명\nINV-001,입고\n".encode() + b"INV-002,\xff\xfe\x80\n"
        )
        with pytest.raises(UnsupportedInput, match="3번째 줄"):
            read_csv(path, "doc-1")

    def test_header_only_csv_is_rejected_as_empty_form(self, tmp_path: Path) -> None:
        path = tmp_path / "h.csv"
        path.write_text("요구사항 ID,요구사항명,상세 내용\n", encoding="utf-8")
        with pytest.raises(UnsupportedInput, match="요구사항이 없는 빈 양식이에요"):
            read_csv(path, "doc-1")

    def test_utf16_with_bom(self, tmp_path: Path) -> None:
        """엑셀 「유니코드 텍스트」로 저장한 UTF-16 CSV도 읽는다."""
        path = tmp_path / "u.csv"
        path.write_bytes("요구사항 ID\t요구사항명\nINV-001\t입고\n".encode("utf-16"))
        [req] = read_csv(path, "doc-1").requirements
        assert req.source_id == "INV-001"

    def test_no_header_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "c.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        with pytest.raises(UnsupportedInput, match="요구사항 표를 찾지 못했어요"):
            read_csv(path, "doc-1")
