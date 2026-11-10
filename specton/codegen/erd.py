"""ERD: 정리된 모델 → Mermaid `erDiagram` (#13, ADR-0004, TC-F10).

입력은 모델 정리(#12) 결과(`NormalizedModel`: 테이블·컬럼·FK)와 설계 관계(`Relationship`)다.
정리 결과에는 카디널리티·선택·식별 여부가 없어 FK의 `relationship_id`로 관계를 찾아 잇는다.
N:M은 정리 단계에서 연결 테이블과 FK 둘로 바뀌어 있으므로 그대로 FK마다 선 하나를 그린다.

- 표기 (#13 결정, A안): 엔티티는 물리명을 식별자로, 한글 이름을 별칭으로 둔다.
  속성은 `타입 한글이름 키 "물리명"`이다. 예: `varchar(20) 창고코드 PK "wrhus_cd"`
- 웹(mermaid JS)·PDF(mermaid-cli)가 같은 원문을 쓴다. 둘 다 Mermaid 11.17.2로 고정한다 (ADR-0004).
- 같은 입력이면 항상 같은 문자열이다 (테이블·FK는 정리 결과의 ID 순서를 따른다).
- 이 모듈은 LLM client를 import하지 않는다 (CLAUDE.md, `codegen/` 규칙).
"""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from specton.contracts.base import Cardinality
from specton.contracts.design import Relationship
from specton.contracts.normalized import Column, NormalizedModel, Table

# Mermaid erDiagram이 받는 속성 이름·타입 글자 (11.15.0 실측 #13 댓글, 11.17.2 재실측 #212 검토).
# 글자·숫자·`_`·`-`·괄호·대괄호를 받되 숫자·`-`·괄호·대괄호로 시작하면 안 된다.
# 공백·`·`·`/`는 파싱 오류다. `.`·`,`는 11.17.2는 받지만 11.15.0에서 오류여서 쓰지 않는다.
_NAME_BAD = re.compile(r"[^\w\-()\[\]]")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Mermaid ER 문법의 단독 키워드 (11.15.0·11.17.2 실측 같음).
# PostgreSQL 예약어와 별개이며 대소문자를 구분하지 않는다.
_MERMAID_KEYWORDS = frozenset({"erdiagram", "style", "classdef", "class", "one", "many", "to"})


# Mermaid erDiagram 배치 방향
Direction = Literal["TB", "BT", "LR", "RL"]


def _direction_line(direction: Direction | None) -> list[str]:
    return [f"    direction {direction}"] if direction else []


@dataclass(frozen=True)
class ErdEdge:
    """ERD 선 하나 = 정리 결과의 FK 하나. `relationship_id`로 설계 관계와 이어진다 (TC-F10)."""

    foreign_key_id: str
    relationship_id: str
    parent_table_id: str
    child_table_id: str
    parent_marker: str  # 자식 한 행에 대한 부모 수: `||` 정확히 하나, `|o` 없거나 하나
    child_marker: str  # 부모 한 행에 대한 자식 수: `o{` 없거나 여럿, `o|` 없거나 하나
    line: str  # `--` 식별 관계(자식 PK에 부모 키 포함), `..` 비식별


def erd_edges(model: NormalizedModel, relationships: Sequence[Relationship]) -> tuple[ErdEdge, ...]:
    """FK마다 선 하나. FK가 가리키는 관계가 없으면 입력이 서로 맞지 않는 것이므로 멈춘다."""
    by_id = {r.id: r for r in relationships}
    tables = {t.id: t for t in model.tables}
    edges: list[ErdEdge] = []
    for fk in model.foreign_keys:
        rel = by_id.get(fk.relationship_id)
        if rel is None:
            raise ValueError(f"{fk.id}: 설계에 없는 관계를 가리킵니다 ({fk.relationship_id})")
        child = tables[fk.table_id]
        if child.relationship_id == rel.id:
            # N:M 연결 테이블: 연결 행은 부모 없이 없고, 부모 한 행에 연결 행이 여럿
            parent_marker, child_marker = "||", "o{"
            identifying = set(fk.columns) <= set(child.primary_key)
        else:
            parent_marker = "|o" if rel.optional else "||"
            child_marker = "o|" if rel.cardinality is Cardinality.ONE_TO_ONE else "o{"
            identifying = rel.identifying
        edges.append(
            ErdEdge(
                foreign_key_id=fk.id,
                relationship_id=rel.id,
                parent_table_id=fk.parent_table_id,
                child_table_id=fk.table_id,
                parent_marker=parent_marker,
                child_marker=child_marker,
                line="--" if identifying else "..",
            )
        )
    return tuple(edges)


def render_erd(
    model: NormalizedModel,
    relationships: Sequence[Relationship],
    *,
    attributes: bool = True,
    labels: bool = True,
    direction: Direction | None = None,
) -> str:
    """Mermaid `erDiagram` 원문.

    `attributes=False`면 속성 없이 엔티티와 관계만 그린다 (전체 관계 개요).
    `labels=False`면 관계선에 관계 ID(`REL-xx`)를 쓰지 않는다(빈 이름 `""`). Mermaid는 이름을 선의
    가운데에 두어, 부모 둘이 같은 자식으로 모이면 두 이름이 겹친다 (#261). PDF 개요가 쓴다.
    `direction`을 주면 배치 방향을 정한다 (`LR`: 좌우, ADR-0004 PDF 상세도).
    """
    idents = _identifiers(model.tables)
    lines = ["erDiagram", *_direction_line(direction)]
    lines.append(f"    %% Specton ERD · {_alias(model.pack)} {_alias(model.pack_version)}")
    fk_columns = {c for fk in model.foreign_keys for c in fk.columns}
    for table in model.tables:
        head = f'    {idents[table.id]}["{_alias(table.name)}"]'
        if not attributes:
            lines.append(head)
            continue
        lines.append(head + " {")
        lines.extend(f"        {_attribute(table, col, fk_columns)}" for col in table.columns)
        lines.append("    }")
    for edge in erd_edges(model, relationships):
        parent, child = idents[edge.parent_table_id], idents[edge.child_table_id]
        marker = f"{edge.parent_marker}{edge.line}{edge.child_marker}"
        label = edge.relationship_id if labels else ""
        lines.append(f'    {parent} {marker} {child} : "{label}"')
    return "\n".join(lines) + "\n"


def _identifiers(tables: Sequence[Table]) -> dict[str, str]:
    """엔티티 식별자: 물리명(영문 소문자). 테이블마다 서로 다르다 (#177 리뷰).

    Mermaid가 받지 못하거나 앞 테이블과 겹치는 물리명은 순번 `t002`로 대신한다.
    쓸 수 있는 물리명을 먼저 모두 잡아 두고 대체 ID를 고르므로, 대체 ID가 다른 테이블의
    물리명(앞이든 뒤든)이나 다른 대체 ID와 겹치지 않는다. 겹치면 `t002_2`처럼 뒤에 번호를 붙인다.
    """
    idents: dict[str, str] = {}
    used: set[str] = set()
    for table in tables:  # 1차: 쓸 수 있는 물리명. 같은 이름이면 먼저 나온 테이블이 갖는다
        name = table.physical_name
        if _IDENT.match(name) and name.lower() not in _MERMAID_KEYWORDS and name not in used:
            idents[table.id] = name
            used.add(name)
    for index, table in enumerate(tables, 1):  # 2차: 남은 테이블에 겹치지 않는 대체 ID
        if table.id in idents:
            continue
        base = candidate = f"t{index:03d}"
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        idents[table.id] = candidate
        used.add(candidate)
    return idents


def _breaks_line(ch: str) -> bool:
    """제어·서식 문자와 줄·문단 구분 문자."""
    category = unicodedata.category(ch)
    return category[0] == "C" or category in ("Zl", "Zp")


def _alias(name: str) -> str:
    """엔티티 별칭·설명에 넣는 사용자 글자. 따옴표 안이라도 Mermaid가 읽는 기호를 걸러 낸다.

    - 큰따옴표는 Mermaid 파싱 오류라 작은따옴표로 바꾼다.
    - `%%`는 지시문(`%%{init: ...}%%`)과 주석의 시작이라 `%`로 줄인다. 따옴표 안의 `init` 지시문도
      strict에서 인식된 것을 R1이 실험으로 확인했다 (#190 리뷰, ADR-0004 「Mermaid 설정 보안」).
    - 줄바꿈·제어 문자(줄·문단 구분 문자 U+2028·U+2029 포함)는 새 줄로 `style`·`classDef` 같은
      문장을 끼워 넣을 수 있어 공백으로 바꾼다.
    """
    text = "".join(" " if _breaks_line(ch) else ch for ch in name)
    while "%%" in text:
        text = text.replace("%%", "%")
    return text.replace('"', "'")


def _attribute(table: Table, col: Column, fk_columns: set[str]) -> str:
    """`타입 이름 키 "설명"` 한 줄. 설명에는 물리명과, 이름·타입에 못 쓴 원래 표기를 남긴다."""
    data_type, type_note = _data_type(col)
    name = _attribute_name(col.name)
    keys = [
        key
        for key, applies in (
            ("PK", col.id in table.primary_key),
            ("FK", col.id in fk_columns),
            ("UK", any(col.id in unique for unique in table.unique_keys)),
        )
        if applies
    ]
    notes = [col.physical_name]
    if type_note:
        notes.append(type_note)
    if name != col.name:
        notes.append(col.name)
    comment = _alias(" · ".join(notes))
    key_text = f" {','.join(keys)}" if keys else ""
    return f'{data_type} {name}{key_text} "{comment}"'


def _data_type(col: Column) -> tuple[str, str | None]:
    """타입 표기와 설명에 따로 적을 자릿수. `numeric(12,2)`의 쉼표는 Mermaid가 받지 않는다."""
    base = col.data_type.value
    if col.length is not None:
        return f"{base}({col.length})", None
    if col.time_precision is not None:
        return f"{base}({col.time_precision})", None
    if col.precision is not None:
        if col.scale is None:
            return f"{base}({col.precision})", None
        return base, f"{base}({col.precision},{col.scale})"
    return base, None


def _attribute_name(name: str) -> str:
    """Mermaid가 받는 속성 이름. 못 쓰는 글자는 `_`로, 첫 글자가 부적합하면 `_`를 붙인다."""
    cleaned = _NAME_BAD.sub("_", name)
    if not cleaned or cleaned[0].isdigit() or cleaned[0] in "-()[]":
        return f"_{cleaned}"
    return cleaned
