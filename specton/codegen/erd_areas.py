"""ERD 업무 영역 나누기 (#13): 테이블을 이름에 든 낱말로 영역에 넣는다.

PDF는 전체 관계 개요 한 장과 업무 영역별 상세 ERD로 나눠 그린다 (#13 R1 결정).
영역과 낱말은 도메인 정보라 팩의 `erd_areas.yaml`에서 받고 여기에 적지 않는다 (`pack_areas`).

배정 규칙 (#13 댓글 6702688564):
- 비교 대상은 정리 결과의 한글 `name`이다. 물리명은 바뀔 수 있어 쓰지 않는다.
- 이름에 든 낱말 가운데 가장 긴 낱말의 영역에 넣는다. 길이가 같으면 먼저 적힌 영역에 넣는다.
  예: 「설비변경이력」은 `설비`(설비·조직)보다 긴 `변경이력`(보전 작업)으로 간다.
- 어디에도 걸리지 않으면 「기타」에 넣는다. 호출자는 `unassigned`로 경고한다.
- 띄어쓰기와 유니코드 조합 차이(NFC/NFD)는 무시한다.

같은 입력이면 항상 같은 결과다. 이 모듈은 LLM client를 import하지 않는다 (CLAUDE.md).
"""

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# 표기 규칙(A안·Mermaid 글자 제한)은 전체 ERD와 같아야 하므로 erd.py의 것을 그대로 쓴다
from specton.codegen.erd import ErdEdge, _alias, _attribute, _identifiers, erd_edges
from specton.contracts.design import Relationship
from specton.contracts.normalized import NormalizedModel, Table
from specton.packs.build import DEFAULT_ROOT
from specton.packs.loader import PackError, load_erd_areas

OTHER_AREA = "기타"


def _compact(text: str) -> str:
    """비교용 표기: NFC로 맞추고 띄어쓰기를 지운다."""
    return "".join(unicodedata.normalize("NFC", text).split())


@dataclass(frozen=True)
class ErdArea:
    """업무 영역 하나. `words` 중 하나가 테이블 이름에 들어 있으면 이 영역 후보다."""

    name: str
    words: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("영역 이름이 비어 있습니다")
        if self.name == OTHER_AREA:
            raise ValueError(f"「{OTHER_AREA}」는 영역 이름으로 쓸 수 없습니다")
        if not self.words:
            raise ValueError(f"{self.name}: 낱말이 없습니다")
        if any(not _compact(word) for word in self.words):
            raise ValueError(f"{self.name}: 빈 낱말이 있습니다")


@dataclass(frozen=True)
class AreaSplit:
    """배정 결과.

    - `areas`: 그릴 순서대로 (영역 이름, 테이블 ID들). 영역은 적힌 순서이고 빈 영역은 뺀다.
      「기타」는 맨 뒤다. 테이블 ID는 입력 순서를 따르고, 모든 테이블이 정확히 한 영역에 들어간다.
    - `unassigned`: 「기타」로 간 테이블 ID (경고용).
    """

    areas: tuple[tuple[str, tuple[str, ...]], ...]
    unassigned: tuple[str, ...]

    def area_of(self, table_id: str) -> str:
        for name, table_ids in self.areas:
            if table_id in table_ids:
                return name
        raise KeyError(table_id)

    def tables_of(self, area: str) -> tuple[str, ...]:
        for name, table_ids in self.areas:
            if name == area:
                return table_ids
        raise KeyError(area)


def pack_areas(pack: str, *, root: Path = DEFAULT_ROOT) -> tuple[ErdArea, ...]:
    """팩의 ERD 업무 영역. 파일이 없으면 빈 목록(영역을 나누지 않음)이다.

    영역 이름이 「기타」이거나 겹치고, 같은 낱말이 두 영역에 있으면 팩 오류로 멈춘다.
    """
    try:
        areas = tuple(ErdArea(a.name, a.words) for a in load_erd_areas(pack, root=root))
        _check_areas(areas)
    except PackError:
        raise
    except ValueError as exc:
        raise PackError(f"{root / pack / 'erd_areas.yaml'}: {exc}") from exc
    return areas


def area_for_name(name: str, areas: Sequence[ErdArea]) -> str:
    """이름 하나의 영역. 가장 긴 낱말이 이기고, 길이가 같으면 먼저 적힌 영역이 이긴다."""
    target = _compact(name)
    best: tuple[int, int] | None = None  # (-낱말 길이, 영역 순서): 작을수록 우선
    best_area = OTHER_AREA
    for order, area in enumerate(areas):
        for word in area.words:
            word = _compact(word)
            if word in target and (best is None or (-len(word), order) < best):
                best, best_area = (-len(word), order), area.name
    return best_area


def assign_areas(tables: Sequence[Table], areas: Sequence[ErdArea]) -> AreaSplit:
    """테이블마다 영역 하나. 영역 목록이 서로 겹치게 적혀 있으면 멈춘다."""
    _check_areas(areas)
    members: dict[str, list[str]] = {area.name: [] for area in areas}
    members[OTHER_AREA] = []
    for table in tables:
        members[area_for_name(table.name, areas)].append(table.id)
    ordered = [area.name for area in areas] + [OTHER_AREA]
    return AreaSplit(
        areas=tuple((name, tuple(members[name])) for name in ordered if members[name]),
        unassigned=tuple(members[OTHER_AREA]),
    )


def _check_areas(areas: Sequence[ErdArea]) -> None:
    """영역 이름이 겹치거나 같은 낱말이 두 영역에 있으면 어느 쪽인지 정할 수 없다."""
    seen_names: set[str] = set()
    owner: dict[str, str] = {}
    for area in areas:
        if area.name in seen_names:
            raise ValueError(f"영역 이름이 겹칩니다: {area.name}")
        seen_names.add(area.name)
        for word in area.words:
            key = _compact(word)
            if owner.get(key, area.name) != area.name:
                raise ValueError(f"낱말 「{key}」가 두 영역에 있습니다: {owner[key]}, {area.name}")
            owner[key] = area.name


# ── 영역별 상세 ERD ───────────────────────────────────────


def area_edges(edges: Sequence[ErdEdge], split: AreaSplit, area: str) -> tuple[ErdEdge, ...]:
    """영역 상세도에 그릴 선: 한쪽 끝이라도 이 영역 테이블이면 그린다.

    영역을 넘는 선은 양쪽 영역 상세도에 모두 나온다. 그래서 모든 영역의 선을 합치면
    전체 선과 같고, 빠지는 선이 없다 (TC-F10).
    """
    members = set(split.tables_of(area))
    return tuple(e for e in edges if e.parent_table_id in members or e.child_table_id in members)


def render_area_erd(
    model: NormalizedModel, relationships: Sequence[Relationship], split: AreaSplit, area: str
) -> str:
    """영역 하나의 상세 ERD (Mermaid `erDiagram`).

    - 이 영역 테이블: 속성까지 그린다 (A안, 전체 ERD와 같은 표기).
    - 선으로 이어진 다른 영역 테이블: 속성 없는 상자로, 이름 뒤에 영역을 붙인다.
      예: `품목 (→ 기준정보)`
    - 식별자는 전체 ERD와 같아서 상세도끼리 같은 테이블은 같은 이름이다.
    """
    members = set(split.tables_of(area))
    edges = area_edges(erd_edges(model, relationships), split, area)
    linked = {t for e in edges for t in (e.parent_table_id, e.child_table_id)} - members
    idents = _identifiers(model.tables)
    fk_columns = {c for fk in model.foreign_keys for c in fk.columns}
    lines = [
        "erDiagram",
        f"    %% Specton ERD · {model.pack} {model.pack_version} · {_alias(area)}",
    ]
    for table in model.tables:
        if table.id in members:
            lines.append(f'    {idents[table.id]}["{_alias(table.name)}"] {{')
            lines.extend(f"        {_attribute(table, col, fk_columns)}" for col in table.columns)
            lines.append("    }")
        elif table.id in linked:
            label = f"{table.name} (→ {split.area_of(table.id)})"
            lines.append(f'    {idents[table.id]}["{_alias(label)}"]')
    for edge in edges:
        parent, child = idents[edge.parent_table_id], idents[edge.child_table_id]
        marker = f"{edge.parent_marker}{edge.line}{edge.child_marker}"
        lines.append(f'    {parent} {marker} {child} : "{edge.relationship_id}"')
    return "\n".join(lines) + "\n"
