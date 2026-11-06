"""DDL 생성 (#15): 정리 결과(`NormalizedModel`) → PostgreSQL DDL 문자열. **임시 구현.**

문장은 두 종류만 만든다.
- `CREATE TABLE`: 칸, `NOT NULL`, `PRIMARY KEY`, `UNIQUE`
- `ALTER TABLE ... ADD FOREIGN KEY`: 모든 표를 만든 뒤 FK를 모아 붙인다. 표 순서·자기참조·순환
  참조와 상관없이 실행 순서가 깨지지 않는다.

규칙 상태:
- 확정 (문서): 허용 타입 11개(docs/05), 물리명은 소문자·`max_bytes` 이하(naming.yaml,
  RATIONALE.md), DDL에 대상·모델 버전·검증 상태를 남김(docs/10)
- R4 제안 (#15 확인 전): 제약 이름을 짓지 않고 PostgreSQL 자동 이름을 씀, `COMMENT ON` 없음,
  식별자는 항상 큰따옴표, 생성 직후 검증 상태는 `unverified`, 반환형 `DdlResult`는 공용 계약
  밖의 임시 모양
- 한계: 자동 제약 이름의 충돌·63바이트 잘림과 실제 실행 가능 여부는 격리 DB 실행(#15 후속)에서
  확인한다. 이 모듈은 문장을 만들 뿐 실행하지 않는다.

같은 입력이면 같은 SQL이다. 표와 FK는 ID 순으로 쓰고, 칸은 `Table.columns` 순서를 그대로 둔다.
SQL로 내보낼 수 없는 값은 고쳐 쓰지 않고 `ValueError`로 멈춘다.
이 모듈은 LLM client를 import하지 않는다.
"""

import unicodedata
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from specton.codegen.model import Column, ForeignKey, NormalizedModel, Table
from specton.contracts.base import SqlType

# 생성기 버전. 출력 모양(문장 종류·순서·타입 표기)이 바뀌면 올린다. 임시 값이다.
DDL_GENERATOR_VERSION = "ddl-v0"
# 대상 DB. 프로젝트 대상 버전(docs/10, naming.yaml 예약어 목록 postgresql_18)과 같다.
DDL_TARGET = "postgresql-18"
# PostgreSQL 18 식별자 한도(NAMEDATALEN - 1). 팩의 max_bytes는 이 값을 넘을 수 없다.
# 넘으면 PostgreSQL이 긴 이름을 잘라, 생성기가 다르다고 본 두 이름이 같은 이름이 된다.
POSTGRES_MAX_IDENTIFIER_BYTES = 63

_LENGTH_TYPES = frozenset({SqlType.CHAR, SqlType.VARCHAR})
_TIME_TYPES = frozenset({SqlType.TIME, SqlType.TIMESTAMP, SqlType.TIMESTAMPTZ})
# PostgreSQL 시각 타입의 소수 초 자릿수 범위 (PostgreSQL 18 문서 8.5)
_TIME_PRECISION_RANGE = range(0, 7)
# `--` 주석은 줄바꿈에서 끝난다. 머리말 값에 이 글자가 있으면 다음 줄이 SQL 문장이 된다.
_HEADER_FORBIDDEN = ("\r", "\n", "\0")


class DdlResult(BaseModel):
    """DDL 생성 결과. 공용 계약(`specton.contracts`)이 아닌 임시 반환형이다.

    산출물 기록(`ArtifactRef`)과 합치는 방식은 R1·R3와 정한다. 내용 해시는 만들지 않는다
    (`ArtifactRef.hash`는 기록하는 쪽이 `sql`로 계산).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    sql: str
    target: str
    generator_version: str
    pack: str
    pack_version: str
    rules_version: str
    lexicon_digest: str
    validation_state: Literal["unverified"]  # 생성 직후 값. 검증 뒤 갱신 방식은 R1과 정한다


def generate_ddl(model: NormalizedModel, *, max_bytes: int) -> DdlResult:
    """정리 결과를 DDL로 바꾼다.

    `max_bytes`는 naming.yaml `physical_name.max_bytes`다 (`load_naming_rules().max_bytes`).
    """
    if not 1 <= max_bytes <= POSTGRES_MAX_IDENTIFIER_BYTES:
        raise ValueError(
            f"max_bytes는 1 이상 {POSTGRES_MAX_IDENTIFIER_BYTES} 이하여야 함 ({max_bytes})"
        )
    _check_header(model)
    tables = {t.id: t for t in model.tables}
    if len(tables) != len(model.tables):
        raise ValueError("테이블 ID가 겹침")
    _check_unique([t.physical_name for t in model.tables], "테이블 물리명")

    statements = [_create_table(t, max_bytes) for t in sorted(model.tables, key=lambda t: t.id)]
    fk_ids = [fk.id for fk in model.foreign_keys]
    _check_unique(fk_ids, "FK ID")
    statements += [
        _add_foreign_key(fk, tables) for fk in sorted(model.foreign_keys, key=lambda fk: fk.id)
    ]
    sql = "\n\n".join([_header(model), *statements]) + "\n"
    return DdlResult(
        sql=sql,
        target=DDL_TARGET,
        generator_version=DDL_GENERATOR_VERSION,
        pack=model.pack,
        pack_version=model.pack_version,
        rules_version=model.rules_version,
        lexicon_digest=model.lexicon_digest,
        validation_state="unverified",
    )


# ── 머리말 ───────────────────────────────────────────────────────────


def _check_header(model: NormalizedModel) -> None:
    for field in ("pack", "pack_version", "rules_version", "lexicon_digest"):
        value: str = getattr(model, field)
        if any(ch in value for ch in _HEADER_FORBIDDEN):
            raise ValueError(f"머리말 값 {field}에 줄바꿈·NUL이 있음: {value!r}")


def _header(model: NormalizedModel) -> str:
    target = DDL_TARGET.replace("-", " ")
    return (
        f"-- {target} / pack {model.pack} {model.pack_version} / rules {model.rules_version}"
        f" / lexicon {model.lexicon_digest} / generator {DDL_GENERATOR_VERSION}"
        " / validation unverified"
    )


# ── 문장 ─────────────────────────────────────────────────────────────


def _create_table(table: Table, max_bytes: int) -> str:
    where = f"테이블 {table.id}"
    name = _ident(table.physical_name, where, max_bytes)
    columns = {c.id: c for c in table.columns}
    if len(columns) != len(table.columns):
        raise ValueError(f"{where}: 칸 ID가 겹침")
    if not columns:
        raise ValueError(f"{where}: 칸이 없음")
    _check_unique([c.physical_name for c in table.columns], f"{where}의 칸 물리명")
    if not table.primary_key:
        raise ValueError(f"{where}: PK가 없음")

    lines = [_column_line(c, max_bytes) for c in table.columns]
    pk = _column_list(table.primary_key, columns, f"{where} PK")
    for col_id in table.primary_key:
        if columns[col_id].nullable:
            raise ValueError(f"{where}: PK 칸 {col_id}가 NULL 허용")
    lines.append(f"PRIMARY KEY ({pk})")
    for group in table.unique_keys:
        lines.append(f"UNIQUE ({_column_list(group, columns, f'{where} UNIQUE')})")
    body = ",\n".join(f"  {line}" for line in lines)
    return f"CREATE TABLE {name} (\n{body}\n);"


def _column_line(column: Column, max_bytes: int) -> str:
    where = f"칸 {column.id}"
    name = _ident(column.physical_name, where, max_bytes)
    null = " NOT NULL" if not column.nullable else ""
    return f"{name} {_sql_type(column)}{null}"


def _add_foreign_key(fk: ForeignKey, tables: dict[str, Table]) -> str:
    where = f"FK {fk.id}"
    child = tables.get(fk.table_id)
    parent = tables.get(fk.parent_table_id)
    if child is None or parent is None:
        raise ValueError(f"{where}: 자식 또는 부모 테이블이 모델에 없음")
    if not fk.columns or len(fk.columns) != len(fk.parent_columns):
        raise ValueError(f"{where}: 자식 칸 수와 부모 칸 수가 다름")
    child_cols = _column_list(fk.columns, {c.id: c for c in child.columns}, where)
    parent_by_id = {c.id: c for c in parent.columns}
    parent_cols = _column_list(fk.parent_columns, parent_by_id, where)
    # PostgreSQL은 부모 칸 묶음에 PK나 UNIQUE가 있어야 FK를 만든다.
    # 파싱으로는 알 수 없어 여기서 본다.
    keys = [set(parent.primary_key), *(set(g) for g in parent.unique_keys)]
    if set(fk.parent_columns) not in keys:
        raise ValueError(f"{where}: 부모 칸 묶음이 부모의 PK·UNIQUE가 아님")
    return (
        f"ALTER TABLE {_quote(child.physical_name)} ADD FOREIGN KEY ({child_cols})"
        f" REFERENCES {_quote(parent.physical_name)} ({parent_cols});"
    )


def _column_list(col_ids: Iterable[str], columns: dict[str, Column], where: str) -> str:
    names = []
    col_ids = tuple(col_ids)
    if not col_ids:
        raise ValueError(f"{where}: 칸 묶음이 비어 있음")
    for col_id in col_ids:
        column = columns.get(col_id)
        if column is None:
            raise ValueError(f"{where}: 칸 {col_id}가 테이블에 없음")
        names.append(_quote(column.physical_name))
    if len(set(names)) != len(names):
        raise ValueError(f"{where}: 같은 칸이 두 번 들어 있음")
    return ", ".join(names)


# ── 타입 ─────────────────────────────────────────────────────────────


def _sql_type(column: Column) -> str:
    """칸 타입 표기. 계약(`Column`)은 타입별 매개변수를 검사하지 않으므로 여기서 본다.

    0과 None을 구분한다: `time(0)`·`numeric(10,0)`의 0은 생략하지 않는다.
    """
    where = f"칸 {column.id}"
    kind = SqlType(column.data_type)  # 허용 타입 11개 밖이면 ValueError
    length, precision, scale, time_precision = (
        column.length,
        column.precision,
        column.scale,
        column.time_precision,
    )
    if kind in _LENGTH_TYPES:
        if length is None or length < 1:
            raise ValueError(f"{where}: {kind.value}에는 양수 length가 필요함 ({length})")
    elif length is not None:
        raise ValueError(f"{where}: {kind.value}에는 length를 쓰지 않음")
    if kind is SqlType.NUMERIC:
        if precision is not None and precision < 1:
            raise ValueError(f"{where}: precision은 양수여야 함 ({precision})")
        if scale is not None and (precision is None or not 0 <= scale <= precision):
            raise ValueError(f"{where}: scale은 0 이상 precision 이하여야 함 ({precision},{scale})")
    elif precision is not None or scale is not None:
        raise ValueError(f"{where}: precision·scale은 numeric에만 씀")
    if kind in _TIME_TYPES:
        if time_precision is not None and time_precision not in _TIME_PRECISION_RANGE:
            raise ValueError(f"{where}: time_precision은 0~6이어야 함 ({time_precision})")
    elif time_precision is not None:
        raise ValueError(f"{where}: time_precision은 시각 타입에만 씀")

    if kind in _LENGTH_TYPES:
        return f"{kind.value}({length})"
    if kind is SqlType.NUMERIC and precision is not None:
        return f"numeric({precision})" if scale is None else f"numeric({precision},{scale})"
    if kind in _TIME_TYPES and time_precision is not None:
        return f"{kind.value}({time_precision})"
    return kind.value


# ── 식별자 ───────────────────────────────────────────────────────────


def _ident(name: str, where: str, max_bytes: int) -> str:
    """물리명 검사 후 큰따옴표로 감싼다. 따옴표는 예약어 충돌만 막고 이름 규칙을 대신하지 않는다."""
    if not name:
        raise ValueError(f"{where}: 물리명이 비어 있음")
    if '"' in name or any(unicodedata.category(ch) == "Cc" for ch in name):
        raise ValueError(f"{where}: 물리명에 큰따옴표·제어 문자가 있음: {name!r}")
    if name != name.lower():
        raise ValueError(f"{where}: 물리명은 소문자여야 함 (naming.yaml ddl_case): {name}")
    size = len(name.encode("utf-8"))
    if size > max_bytes:
        raise ValueError(f"{where}: 물리명 {name}이 {size}바이트 > {max_bytes}")
    return _quote(name)


def _quote(name: str) -> str:
    return f'"{name}"'


def _check_unique(names: list[str], what: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"{what}이 겹침: {name}")
        seen.add(name)
