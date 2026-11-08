"""ERD 업무 영역 나누기 (#13): 테이블 이름의 낱말로 영역을 정한다.

- 가장 긴 낱말이 이기고, 길이가 같으면 먼저 적힌 영역이 이긴다 (#13 댓글 6702688564)
- 어디에도 안 걸리면 「기타」, 경고용 목록에 남는다
- 모든 테이블이 정확히 한 영역에 들어간다
- 영역별 상세도의 선을 모두 합치면 전체 ERD의 선과 같다 (TC-F10)

낱말 목록은 이 테스트용 예시다. 실제 목록은 팩의 `erd_areas.yaml`에서 온다 (#166 뒤).
"""

import re
import unicodedata
from typing import Any

import pytest

# 전체 ERD 테스트의 시험 모델(테이블 8개·FK 6개)을 그대로 나눠 본다
from test_erd import MODEL, RELATIONSHIPS, _edge_lines

from specton.codegen.erd import erd_edges, render_erd
from specton.codegen.erd_areas import (
    OTHER_AREA,
    ErdArea,
    area_edges,
    area_for_name,
    assign_areas,
    render_area_erd,
)
from specton.contracts.normalized import Table

# 유경님 초안(#13 댓글 6683328802)을 줄여 만든 시험용 목록
BASE = ErdArea("기준정보", ("창고", "품목", "자재"))
FLOW = ErdArea("수불", ("수불", "입고", "출고", "투입"))
HISTORY = ErdArea("재고 이력", ("이력", "실사", "조정", "로트", "수정기록"))
AREAS = (BASE, FLOW, HISTORY)


def _table(tid: str, name: str) -> Table:
    data: dict[str, Any] = {
        "id": tid,
        "name": name,
        "physical_name": f"t_{tid.lower().replace('-', '_')}",
        "columns": [],
        "primary_key": [],
        "unique_keys": [],
        "req_ids": ["REQ-01"],
    }
    return Table.model_validate(data)


# ── 이름 하나 ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "area"),
    [
        ("창고", "기준정보"),
        ("입고", "수불"),
        ("재고실사", "재고 이력"),
    ],
)
def test_a_word_in_the_name_picks_its_area(name: str, area: str) -> None:
    assert area_for_name(name, AREAS) == area


def test_the_longest_word_wins() -> None:
    """「설비변경이력」은 설비(2글자)보다 변경이력(4글자)의 영역으로 간다."""
    areas = (ErdArea("설비·조직", ("설비", "팀")), ErdArea("보전 작업", ("고장", "변경이력")))
    assert area_for_name("설비변경이력", areas) == "보전 작업"


def test_the_longest_word_wins_even_when_its_area_is_listed_later() -> None:
    assert area_for_name("품목수정기록", AREAS) == "재고 이력"  # 수정기록(4) > 품목(2)


def test_names_with_the_same_length_words_go_to_the_area_listed_first() -> None:
    assert area_for_name("창고입고", AREAS) == "기준정보"
    assert area_for_name("창고입고", (FLOW, BASE, HISTORY)) == "수불"
    # 품목·입고 모두 2글자라 먼저 적힌 기준정보로 간다. 수불로 보내려면 「입고내역」 같은
    # 더 긴 낱말을 수불에 적는다 (낱말 목록으로 고치는 경우).
    assert area_for_name("품목입고내역", AREAS) == "기준정보"
    assert area_for_name("품목입고내역", (BASE, ErdArea("수불", ("입고내역",)))) == "수불"


def test_a_name_with_no_word_goes_to_other() -> None:
    assert area_for_name("거래처", AREAS) == OTHER_AREA


def test_different_names_a03_gives_the_same_thing_land_in_the_same_area() -> None:
    """A03이 실행마다 이름을 조금 다르게 지어도 같은 영역이다 (#13 댓글 6683328802)."""
    assert area_for_name("재고수정기록", AREAS) == "재고 이력"
    assert area_for_name("재고수량수정기록", AREAS) == "재고 이력"


def test_spaces_and_unicode_composition_do_not_matter() -> None:
    nfd = unicodedata.normalize("NFD", "재고 실사")
    assert nfd != "재고 실사"
    assert area_for_name(nfd, AREAS) == "재고 이력"
    assert area_for_name("품목", (ErdArea("기준정보", ("품 목",)),)) == "기준정보"


def test_an_n_to_m_junction_table_named_after_both_sides_gets_one_area() -> None:
    """정리 단계는 연결 테이블 이름을 부모+자식 이름으로 짓는다 (codegen/normalize.py)."""
    assert area_for_name("품목거래처", AREAS) == "기준정보"


# ── 모델 전체 ─────────────────────────────────────────────

TABLES = (
    _table("TBL-01", "창고"),
    _table("TBL-02", "입고"),
    _table("TBL-03", "거래처"),
    _table("TBL-04", "품목"),
    _table("TBL-05", "재고실사"),
    _table("TBL-06", "출고"),
)


def test_every_table_goes_to_exactly_one_area() -> None:
    split = assign_areas(TABLES, AREAS)
    placed = [tid for _, tids in split.areas for tid in tids]
    assert sorted(placed) == sorted(t.id for t in TABLES)
    assert len(placed) == len(set(placed))


def test_areas_keep_the_listed_order_with_other_last_and_tables_keep_input_order() -> None:
    split = assign_areas(TABLES, AREAS)
    assert split.areas == (
        ("기준정보", ("TBL-01", "TBL-04")),
        ("수불", ("TBL-02", "TBL-06")),
        ("재고 이력", ("TBL-05",)),
        (OTHER_AREA, ("TBL-03",)),
    )
    assert split.unassigned == ("TBL-03",)
    assert split.area_of("TBL-05") == "재고 이력"


def test_empty_areas_are_left_out() -> None:
    split = assign_areas(TABLES[:2], AREAS)
    assert [name for name, _ in split.areas] == ["기준정보", "수불"]
    assert split.unassigned == ()


def test_with_no_areas_everything_is_other() -> None:
    split = assign_areas(TABLES, ())
    assert split.areas == ((OTHER_AREA, tuple(t.id for t in TABLES)),)


def test_unknown_table_id_is_an_error() -> None:
    with pytest.raises(KeyError):
        assign_areas(TABLES, AREAS).area_of("TBL-99")


def test_same_input_same_result() -> None:
    assert assign_areas(TABLES, AREAS) == assign_areas(TABLES, AREAS)


# ── 잘못 적힌 영역 목록 ───────────────────────────────────


@pytest.mark.parametrize(
    ("name", "words", "message"),
    [
        ("", ("창고",), "비어"),
        (OTHER_AREA, ("창고",), OTHER_AREA),
        ("기준정보", (), "낱말이 없"),
        ("기준정보", ("창고", " "), "빈 낱말"),
    ],
)
def test_bad_area_is_rejected(name: str, words: tuple[str, ...], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ErdArea(name, words)


def test_duplicate_area_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="영역 이름이 겹칩니다"):
        assign_areas(TABLES, (BASE, ErdArea("기준정보", ("거래처",))))


def test_the_same_word_in_two_areas_is_rejected() -> None:
    """같은 낱말이 두 영역에 있으면 목록을 고칠 때까지 멈춘다 (어느 쪽인지 정할 수 없음)."""
    with pytest.raises(ValueError, match="「입고」"):
        assign_areas(TABLES, (BASE, FLOW, ErdArea("재고 이력", ("입 고",))))


# ── 영역별 상세 ERD (TC-F10) ──────────────────────────────
# 기준정보: 창고·품목·품목분류·품목사진·품목거래처 / 수불: 입고·입고내역 / 기타: 거래처
# 영역을 넘는 선: 입고→창고(REL-01), 품목거래처→거래처(REL-04의 FK 하나)

SPLIT = assign_areas(MODEL.tables, AREAS)
EDGES = erd_edges(MODEL, RELATIONSHIPS)
AREA_NAMES = [name for name, _ in SPLIT.areas]


def _declared(text: str) -> dict[str, str]:
    """선언된 테이블: 식별자 → 별칭."""
    found = re.findall(r'^    (\w+)\["([^"]*)"\]', text, flags=re.MULTILINE)
    return dict(found)


def test_split_of_the_sample_model() -> None:
    assert SPLIT.areas == (
        ("기준정보", ("TBL-cl", "TBL-it", "TBL-ph", "TBL-wh", "TBL-x4")),
        ("수불", ("TBL-rc", "TBL-rl")),
        (OTHER_AREA, ("TBL-vd",)),
    )


def test_tc_f10_area_edges_together_are_exactly_all_edges() -> None:
    """영역별 상세도의 선을 모두 합치면 전체 선과 같다. 빠지는 선도, 없는 선도 없다."""
    drawn = {e.foreign_key_id for area in AREA_NAMES for e in area_edges(EDGES, SPLIT, area)}
    assert drawn == {fk.id for fk in MODEL.foreign_keys}


def test_an_edge_is_drawn_in_the_areas_of_both_ends_and_nowhere_else() -> None:
    for edge in EDGES:
        ends = {SPLIT.area_of(edge.parent_table_id), SPLIT.area_of(edge.child_table_id)}
        shown = {area for area in AREA_NAMES if edge in area_edges(EDGES, SPLIT, area)}
        assert shown == ends, edge.foreign_key_id


def test_tc_f10_rendered_area_lines_together_match_the_full_erd() -> None:
    """그린 문자열 기준으로도 같다: 영역별 선 줄을 합치면 전체 ERD의 선 줄과 같다."""
    full = set(_edge_lines(render_erd(MODEL, RELATIONSHIPS)))
    by_area = [_edge_lines(render_area_erd(MODEL, RELATIONSHIPS, SPLIT, a)) for a in AREA_NAMES]
    assert set().union(*map(set, by_area)) == full
    crossing = 2  # 입고→창고, 품목거래처→거래처는 두 상세도에 나온다
    assert sum(len(lines) for lines in by_area) == len(full) + crossing


def test_own_tables_have_attributes_and_other_area_tables_are_boxes() -> None:
    text = render_area_erd(MODEL, RELATIONSHIPS, SPLIT, "수불")
    assert _declared(text) == {
        "wrhsg": "입고",
        "wrhsg_dtl": "입고내역",
        "wrhus": "창고 (→ 기준정보)",
    }
    assert 'wrhsg["입고"] {' in text and 'wrhus["창고 (→ 기준정보)"]\n' in text
    assert ' 입고번호 PK "wrhsg_no"' in text
    assert ' 창고코드 PK "wrhus_cd"' not in text  # 다른 영역 상자에는 속성이 없다


def test_every_own_table_is_drawn_even_without_edges() -> None:
    for area, table_ids in SPLIT.areas:
        text = render_area_erd(MODEL, RELATIONSHIPS, SPLIT, area)
        declared = _declared(text)
        for tid in table_ids:
            table = next(t for t in MODEL.tables if t.id == tid)
            assert declared[table.physical_name] == table.name


def test_unconnected_tables_of_other_areas_are_left_out() -> None:
    text = render_area_erd(MODEL, RELATIONSHIPS, SPLIT, OTHER_AREA)
    assert _declared(text) == {"bzpt": "거래처", "item_bzpt": "품목거래처 (→ 기준정보)"}


def test_identifiers_are_the_same_as_in_the_full_erd() -> None:
    full = _declared(render_erd(MODEL, RELATIONSHIPS))
    for area in AREA_NAMES:
        assert set(_declared(render_area_erd(MODEL, RELATIONSHIPS, SPLIT, area))) <= set(full)


def test_area_name_is_in_the_header_comment() -> None:
    text = render_area_erd(MODEL, RELATIONSHIPS, SPLIT, "기준정보")
    assert text.splitlines()[1] == "    %% Specton ERD · inventory 0.1.7 · 기준정보"


def test_unknown_area_is_an_error() -> None:
    with pytest.raises(KeyError):
        render_area_erd(MODEL, RELATIONSHIPS, SPLIT, "설비")


def test_same_input_same_area_text() -> None:
    for area in AREA_NAMES:
        first = render_area_erd(MODEL, RELATIONSHIPS, SPLIT, area)
        assert first == render_area_erd(MODEL, RELATIONSHIPS, SPLIT, area)
