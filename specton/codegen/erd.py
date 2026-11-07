"""ERD: 정리된 모델 → Mermaid `erDiagram` (#13, ADR-0004, TC-F10).

입력은 모델 정리(#12) 결과(`NormalizedModel`: 테이블·컬럼·FK)와 설계 관계(`Relationship`)다.
정리 결과에는 카디널리티·선택·식별 여부가 없어 FK의 `relationship_id`로 관계를 찾아 잇는다.
N:M은 정리 단계에서 연결 테이블과 FK 둘로 바뀌어 있으므로 그대로 FK마다 선 하나를 그린다.

- 표기 (#13 결정, A안): 엔티티는 물리명을 식별자로, 한글 이름을 별칭으로 둔다.
  속성은 `타입 한글이름 키 "물리명"`이다. 예: `varchar(20) 창고코드 PK "wrhus_cd"`
- 웹(mermaid JS)·PDF(mermaid-cli)가 같은 원문을 쓴다. 둘 다 Mermaid 11.15.0으로 고정한다.
- 같은 입력이면 항상 같은 문자열이다 (테이블·FK는 정리 결과의 ID 순서를 따른다).
- 이 모듈은 LLM client를 import하지 않는다 (CLAUDE.md, `codegen/` 규칙).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from specton.contracts.base import Cardinality
from specton.contracts.design import Relationship
from specton.contracts.normalized import Column, NormalizedModel, Table

# Mermaid 11.15.0 erDiagram이 받는 속성 이름·타입 글자 (실측, #13 댓글).
# 글자·숫자·`_`·`-`·괄호·대괄호만 받고, 숫자로 시작하면 안 된다. 공백·`·`·`/`·`.`·`,`는 파싱 오류다.
_NAME_BAD = re.compile(r"[^\w\-()\[\]]")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
    model: NormalizedModel, relationships: Sequence[Relationship], *, attributes: bool = True
) -> str:
    """Mermaid `erDiagram` 원문.

    `attributes=False`면 속성 없이 엔티티와 관계만 그린다 (전체 관계 개요).
    """
    idents = _identifiers(model.tables)
    lines = ["erDiagram", f"    %% Specton ERD · {model.pack} {model.pack_version}"]
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
        lines.append(f'    {parent} {marker} {child} : "{edge.relationship_id}"')
    return "\n".join(lines) + "\n"


def _identifiers(tables: Sequence[Table]) -> dict[str, str]:
    """엔티티 식별자: 물리명(영문 소문자). Mermaid가 받지 못하는 이름이면 순번으로 대신한다."""
    idents: dict[str, str] = {}
    for index, table in enumerate(tables, 1):
        name = table.physical_name
        idents[table.id] = (
            name if _IDENT.match(name) and name not in idents.values() else f"t{index:03d}"
        )
    return idents


def _alias(name: str) -> str:
    """엔티티 별칭(한글 이름). 큰따옴표는 Mermaid 파싱 오류라 작은따옴표로 바꾼다."""
    return name.replace('"', "'")


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
    comment = " · ".join(notes).replace('"', "'")
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
    """Mermaid가 받는 속성 이름. 못 쓰는 글자는 `_`로, 숫자로 시작하면 앞에 `_`를 붙인다."""
    cleaned = _NAME_BAD.sub("_", name)
    return f"_{cleaned}" if cleaned[:1].isdigit() else cleaned
