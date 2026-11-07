"""한글(.hwp·.hwpx) 읽기 시험 (#24 할 일 1번).

구성: (a) 엔진 독립 자료형으로 만든 가짜 문서로 읽는 규칙 시험(원문 없이 돌아감),
(b) 예비 경로(`rhwp dump`) 인자 모양 시험, (c) 비공개 원문이 있을 때만 도는 회귀 시험.

제안(#24 선진행): (c)를 「원문 파일이 없으면 skip」으로 두는 방식은 팀이 정한 것이 아니라 제안이다.
원문은 비공개라 저장소에 넣지 않으므로, 환경변수 `SPECTON_HANGUL_SAMPLES`(없으면 아래
`_DEFAULT_SAMPLES`)에 두 파일이 있을 때만 돌고 없으면 건너뛴다. 시험 데이터에는 원문 글을 길게
복사하지 않고 숫자·고유번호·문단 번호만 고정한다.
"""

import os
import stat
from pathlib import Path

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

_DEFAULT_SAMPLES = Path("/Users/hykim/Desktop/dev/capstone/share/in/2026-10-28_재고자재_RFP")
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

    def test_missing_file_is_not_hidden(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            read_hangul(tmp_path / "없음.hwp", "doc-1")


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


def _samples() -> Path:
    folder = Path(os.environ.get("SPECTON_HANGUL_SAMPLES", _DEFAULT_SAMPLES))
    if not (folder / _KITECH).exists() or not (folder / _GYEONGNAM).exists():
        pytest.skip("비공개 한글 원문 두 파일이 없어 회귀 시험을 건너뜀(SPECTON_HANGUL_SAMPLES)")
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
        import rhwp  # 시험에서 엔진을 직접 쓰는 것은 허용(원본을 hwpx로 내보내려는 용도)

        for name in (_KITECH, _GYEONGNAM):
            exported = tmp_path / (Path(name).stem + ".hwpx")
            rhwp.parse(str(_samples() / name)).export_hwpx(str(exported))
            assert _key_map(exported) == _key_map(_samples() / name)


def test_read_blocks_is_the_only_engine_door() -> None:
    """저장소에서 rhwp를 직접 가져오는 곳은 hangul_engine.py 하나뿐이다(시험 파일 제외)."""
    root = Path(__file__).resolve().parents[2]
    users = [
        p.relative_to(root).as_posix()
        for p in (root / "specton").rglob("*.py")
        if "import rhwp" in p.read_text(encoding="utf-8")
        or "from rhwp" in p.read_text(encoding="utf-8")
    ]
    assert users == ["specton/ingest/hangul_engine.py"]
    assert read_blocks  # 공개 함수 존재 확인
