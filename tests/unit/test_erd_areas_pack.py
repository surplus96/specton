"""팩의 ERD 업무 영역 파일 `erd_areas.yaml` 읽기 (#13, ADR-0004).

- 파일이 없으면 영역을 나누지 않는다(빈 목록). 다른 팩 파일과 달리 오류가 아니다.
- 모양이 틀리거나, 「기타」를 영역 이름으로 쓰거나, 같은 낱말이 두 영역에 있으면 팩 오류다.
- 실제 재고 팩 영역으로 대표 이름이 기대한 영역에 들어간다.
"""

from pathlib import Path

import pytest

from specton.codegen.erd_areas import OTHER_AREA, area_for_name, assign_areas, pack_areas
from specton.contracts.normalized import Table
from specton.packs.loader import PackError, load_erd_areas

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS = REPO_ROOT / "domain_packs"

MANIFEST = """\
name: {name}
version: 0.1.0
description: 시험용 팩
source: 합성 자료
origin: synthetic
status: draft
"""

TWO_AREAS = """\
areas:
  - {name: 수불, words: [입고, 출고]}
  - {name: 기준정보, words: [창고]}
"""

SAME_NAME = """\
areas:
  - {name: 수불, words: [입고]}
  - {name: 수불, words: [출고]}
"""

SAME_WORD = """\
areas:
  - {name: 수불, words: [입고]}
  - {name: 이력, words: ['입 고']}
"""

OTHER_AS_NAME = f"""\
areas:
  - {{name: {OTHER_AREA}, words: [입고]}}
"""

INVENTORY_AREAS = ["수불", "재고 이력", "기준정보"]


def _pack(root: Path, areas: str | None, name: str = "inventory") -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.yaml").write_text(MANIFEST.format(name=name), "utf-8")
    if areas is not None:
        (folder / "erd_areas.yaml").write_text(areas, "utf-8")
    return root


# ── 파일 읽기 (loader) ────────────────────────────────────


def test_no_file_means_no_areas(tmp_path: Path) -> None:
    root = _pack(tmp_path, None)
    assert load_erd_areas("inventory", root=root) == ()
    assert pack_areas("inventory", root=root) == ()


def test_areas_keep_the_written_order(tmp_path: Path) -> None:
    root = _pack(tmp_path, TWO_AREAS)
    assert [(a.name, a.words) for a in load_erd_areas("inventory", root=root)] == [
        ("수불", ("입고", "출고")),
        ("기준정보", ("창고",)),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "areas: []\n",  # 파일을 두려면 영역이 하나 이상
        "areas:\n  - {name: 수불, words: []}\n",  # 낱말 없는 영역
        "areas:\n  - {name: '', words: [입고]}\n",  # 빈 이름
        "areas:\n  - {name: 수불, words: [입고], color: red}\n",  # 모르는 칸
        "areas: [\n",  # YAML 문법 오류
    ],
)
def test_bad_file_shape_is_a_pack_error(tmp_path: Path, text: str) -> None:
    root = _pack(tmp_path, text)
    with pytest.raises(PackError, match="형식이 틀렸습니다"):
        load_erd_areas("inventory", root=root)


def test_missing_or_common_pack_is_a_pack_error(tmp_path: Path) -> None:
    with pytest.raises(PackError):
        load_erd_areas("nothing", root=tmp_path)
    with pytest.raises(PackError, match="선택할 수 있는 팩이 아닙니다"):
        load_erd_areas("common", root=tmp_path)


# ── 영역 규칙 (codegen) ───────────────────────────────────


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (OTHER_AS_NAME, OTHER_AREA),
        (SAME_NAME, "영역 이름이 겹칩니다"),
        (SAME_WORD, "「입고」"),
    ],
)
def test_area_rules_are_checked_when_the_pack_is_read(
    tmp_path: Path, text: str, message: str
) -> None:
    root = _pack(tmp_path, text)
    with pytest.raises(PackError, match=message) as err:
        pack_areas("inventory", root=root)
    assert "erd_areas.yaml" in str(err.value)  # 어느 파일을 고칠지 알려 준다


# ── 실제 팩 ───────────────────────────────────────────────


def test_inventory_pack_has_three_areas_and_maintenance_has_none_yet() -> None:
    assert [a.name for a in pack_areas("inventory", root=PACKS)] == INVENTORY_AREAS
    assert pack_areas("maintenance", root=PACKS) == ()


@pytest.mark.parametrize(
    ("name", "area"),
    [
        ("창고", "기준정보"),
        ("품목분류", "기준정보"),
        ("거래처", "기준정보"),  # 「거래처」(3글자)가 수불의 「거래」(2글자)보다 길다
        ("거래처변경이력", "기준정보"),  # 「거래처」(3글자)가 「이력」보다 길다
        ("보관위치", "기준정보"),
        ("재고거래", "수불"),
        ("재고거래내역", "수불"),
        ("수불문서", "수불"),
        ("입고", "수불"),
        ("이동지시", "수불"),
        ("보관위치배정", "수불"),  # 「위치배정」(4)과 「보관위치」(4)가 같은 길이 → 먼저 적힌 수불
        ("재고", "재고 이력"),
        ("재고실사", "재고 이력"),
        ("재고조정", "재고 이력"),
        ("로트", "재고 이력"),
        ("재고수정기록", "재고 이력"),  # A03이 이름을 조금 다르게 지어도 같은 영역 (#13)
        ("재고수량수정기록", "재고 이력"),
        # 길이가 같으면 먼저 적힌 영역: 기준정보를 맨 뒤에 두어 거래 이름이 기준정보로 가지 않는다
        ("자재투입", "수불"),
        ("창고재고", "재고 이력"),
        ("품목입고내역", "수불"),
        ("표준용어", OTHER_AREA),  # 재고 업무 영역 밖 (SFR-206)
    ],
)
def test_real_inventory_areas_place_representative_names(name: str, area: str) -> None:
    assert area_for_name(name, pack_areas("inventory", root=PACKS)) == area


def test_every_table_of_a_model_gets_an_area_with_the_real_pack() -> None:
    names = ["창고", "품목", "재고거래", "재고거래내역", "재고실사", "표준용어"]
    tables = [
        Table.model_validate(
            {
                "id": f"TBL-{i}",
                "name": n,
                "physical_name": f"t{i}",
                "columns": [],
                "primary_key": [],
                "unique_keys": [],
                "req_ids": ["REQ-01"],
            }
        )
        for i, n in enumerate(names)
    ]
    split = assign_areas(tables, pack_areas("inventory", root=PACKS))
    assert sorted(t for _, ids in split.areas for t in ids) == sorted(t.id for t in tables)
    assert split.unassigned == ("TBL-5",)
