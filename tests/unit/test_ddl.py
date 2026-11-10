"""DDL 생성 (#15). 정리 결과 → PostgreSQL DDL 문자열.

DB에 접속하지 않는다. 문법은 pglast(PostgreSQL 파서)로만 확인한다. 파싱 통과는 실제 실행
성공(자동 제약 이름 충돌, 63바이트 잘림 등)의 증거가 아니며, 실행 확인은 격리 DB 작업에서 한다.
"""

import re
from dataclasses import replace
from typing import Any

import pytest
from pglast import parse_sql
from pglast.ast import AlterTableStmt, ColumnDef, CreateStmt

from specton.codegen.ddl import DDL_GENERATOR_VERSION, DDL_TARGET, DdlResult, generate_ddl
from specton.codegen.model import Column, ForeignKey, Normalized, NormalizedModel, Table
from specton.codegen.naming import load_naming_rules, load_pack_lexicon
from specton.codegen.normalize import PackRef, normalize
from specton.contracts import DesignState, Entity, Relationship, Requirement

MAX_BYTES = load_naming_rules().max_bytes  # 한도는 naming.yaml에서 읽는다


def _col(col_id: str, physical: str, data_type: str = "varchar", **kw: Any) -> Column:
    base: dict[str, Any] = {
        "id": col_id,
        "name": physical,
        "physical_name": physical,
        "data_type": data_type,
        "length": 10 if data_type in ("varchar", "char") else None,
        "precision": None,
        "scale": None,
        "time_precision": None,
        "domain": None,
        "nullable": True,
        "req_ids": ("REQ-01",),
    }
    return Column.model_validate({**base, **kw})


def _key(col_id: str, physical: str, data_type: str = "varchar", **kw: Any) -> Column:
    return _col(col_id, physical, data_type, nullable=False, **kw)


def _table(
    table_id: str,
    physical: str,
    columns: list[Column],
    pk: tuple[str, ...],
    unique: tuple[tuple[str, ...], ...] = (),
) -> Table:
    return Table(
        id=table_id,
        name=physical,
        physical_name=physical,
        columns=tuple(columns),
        primary_key=pk,
        unique_keys=unique,
        req_ids=("REQ-01",),
        entity_id=f"ENT-{table_id}",
    )


def _fk(
    fk_id: str, table: str, cols: tuple[str, ...], parent: str, parent_cols: tuple[str, ...]
) -> ForeignKey:
    return ForeignKey(
        id=fk_id,
        relationship_id=f"REL-{fk_id}",
        table_id=table,
        columns=cols,
        parent_table_id=parent,
        parent_columns=parent_cols,
        req_ids=("REQ-01",),
    )


def _model(
    tables: list[Table], fks: tuple[ForeignKey, ...] | list[ForeignKey] = (), **header: str
) -> NormalizedModel:
    base = {
        "pack": "inventory",
        "pack_version": "0.1.8",
        "rules_version": "normalize-v0",
        "lexicon_digest": "abc123",
    }
    return NormalizedModel.model_validate(
        {**base, **header, "tables": tuple(tables), "foreign_keys": tuple(fks)}
    )


def _copy(obj: Any, **changes: Any) -> Any:
    """검증을 거치지 않은 사본. 계약은 통과하지만 SQL로 내보내면 안 되는 값을 만들 때 쓴다."""
    return obj.model_copy(update=changes)


WAREHOUSE = _table(
    "T1",
    "wrhus",
    [_key("C1", "wrhus_cd"), _col("C2", "wrhus_nm", length=200)],
    ("C1",),
    (("C2",),),
)
RECEIPT = _table(
    "T2",
    "wrhsg",
    [
        _key("C3", "wrhsg_no"),
        _col("C4", "wrhsg_qty", "numeric", precision=15, scale=3),
        _key("C5", "wrhus_cd"),
    ],
    ("C3",),
)
RECEIPT_FK = _fk("F1", "T2", ("C5",), "T1", ("C1",))
BASE = _model([WAREHOUSE, RECEIPT], [RECEIPT_FK])


def _sql(model: NormalizedModel = BASE) -> str:
    return generate_ddl(model, max_bytes=MAX_BYTES).sql


def _statements(sql: str) -> list[Any]:
    return [raw.stmt for raw in parse_sql(sql)]


# ── 출력 모양 ─────────────────────────────────────────────────────────


def test_tables_then_foreign_keys_in_fixed_shape() -> None:
    assert _sql() == (
        "-- postgresql 18 / pack inventory 0.1.8 / rules normalize-v0 / lexicon abc123"
        f" / generator {DDL_GENERATOR_VERSION}\n"
        "\n"
        'CREATE TABLE "wrhus" (\n'
        '  "wrhus_cd" varchar(10) NOT NULL,\n'
        '  "wrhus_nm" varchar(200),\n'
        '  PRIMARY KEY ("wrhus_cd"),\n'
        '  UNIQUE ("wrhus_nm")\n'
        ");\n"
        "\n"
        'CREATE TABLE "wrhsg" (\n'
        '  "wrhsg_no" varchar(10) NOT NULL,\n'
        '  "wrhsg_qty" numeric(15,3),\n'
        '  "wrhus_cd" varchar(10) NOT NULL,\n'
        '  PRIMARY KEY ("wrhsg_no")\n'
        ");\n"
        "\n"
        'ALTER TABLE "wrhsg" ADD FOREIGN KEY ("wrhus_cd") REFERENCES "wrhus" ("wrhus_cd");\n'
    )


def test_result_carries_target_versions_and_unverified_state() -> None:
    result = generate_ddl(BASE, max_bytes=MAX_BYTES)
    assert result.model_dump(exclude={"sql"}) == {
        "target": DDL_TARGET,
        "generator_version": DDL_GENERATOR_VERSION,
        "pack": "inventory",
        "pack_version": "0.1.8",
        "rules_version": "normalize-v0",
        "lexicon_digest": "abc123",
        "validation_state": "unverified",
    }
    with pytest.raises(ValueError):  # 불변
        result.sql = ""  # type: ignore[misc]
    assert isinstance(result, DdlResult)


def test_output_parses_as_only_create_and_alter_table() -> None:
    stmts = _statements(_sql())
    assert [type(s) for s in stmts] == [CreateStmt, CreateStmt, AlterTableStmt]


def test_no_constraint_names_and_no_comment_statements() -> None:
    """제약 이름은 PostgreSQL 자동 이름을 쓰고 COMMENT ON은 넣지 않는다 (R4 제안)."""
    sql = _sql()
    assert "CONSTRAINT" not in sql and "COMMENT" not in sql


# ── FK ───────────────────────────────────────────────────────────────


def test_composite_foreign_key_keeps_order_on_both_sides() -> None:
    parent = _table(
        "T1", "bcnc", [_key("P1", "bzmn_no"), _key("P2", "brnch_sn", "integer")], ("P1", "P2")
    )
    child = _table(
        "T2",
        "wrhsg",
        [_key("C1", "wrhsg_no"), _key("C2", "brnch_sn", "integer"), _key("C3", "bzmn_no")],
        ("C1",),
    )
    # 자식 칸은 테이블 안에서 순서가 달라도 FK의 짝 순서(columns[i] → parent_columns[i])를 따른다
    fk = _fk("F1", "T2", ("C3", "C2"), "T1", ("P1", "P2"))
    sql = _sql(_model([parent, child], [fk]))
    assert (
        'ALTER TABLE "wrhsg" ADD FOREIGN KEY ("bzmn_no", "brnch_sn")'
        ' REFERENCES "bcnc" ("bzmn_no", "brnch_sn");'
    ) in sql
    assert 'PRIMARY KEY ("bzmn_no", "brnch_sn")' in sql


def test_self_reference_foreign_key_on_nullable_column() -> None:
    table = _table("T1", "eqpm", [_key("C1", "eqpm_cd"), _col("C2", "up_eqpm_cd")], ("C1",))
    sql = _sql(_model([table], [_fk("F1", "T1", ("C2",), "T1", ("C1",))]))
    assert '"up_eqpm_cd" varchar(10),' in sql  # NULL 허용 (최상위 행)
    assert 'ALTER TABLE "eqpm" ADD FOREIGN KEY ("up_eqpm_cd") REFERENCES "eqpm" ("eqpm_cd");' in sql


def test_foreign_key_may_reference_a_unique_group() -> None:
    sql = _sql(_model([WAREHOUSE, RECEIPT], [_fk("F1", "T2", ("C3",), "T1", ("C2",))]))
    assert 'REFERENCES "wrhus" ("wrhus_nm")' in sql


def test_several_unique_groups_in_model_order() -> None:
    table = _table(
        "T1",
        "wrhus",
        [_key("C1", "wrhus_cd"), _col("C2", "wrhus_nm"), _col("C3", "bzmn_no")],
        ("C1",),
        (("C3",), ("C2", "C3")),
    )
    sql = _sql(_model([table]))
    assert '  UNIQUE ("bzmn_no"),\n  UNIQUE ("wrhus_nm", "bzmn_no")\n' in sql


# ── 결정성 ───────────────────────────────────────────────────────────


def test_same_input_same_sql_and_list_order_of_tables_and_fks_does_not_matter() -> None:
    other = _table("T3", "dlvr", [_key("C9", "dlvr_no"), _key("C8", "wrhus_cd")], ("C9",))
    fks = [RECEIPT_FK, _fk("F2", "T3", ("C8",), "T1", ("C1",))]
    first = _sql(_model([WAREHOUSE, RECEIPT, other], fks))
    assert first == _sql(_model([other, RECEIPT, WAREHOUSE], fks[::-1]))
    assert first == _sql(_model([WAREHOUSE, RECEIPT, other], fks))


def test_column_order_is_kept_as_designed() -> None:
    swapped = WAREHOUSE.model_copy(update={"columns": WAREHOUSE.columns[::-1]})
    sql = _sql(_model([swapped, RECEIPT], [RECEIPT_FK]))
    assert sql.index('"wrhus_nm" varchar') < sql.index('"wrhus_cd" varchar')
    assert sql != _sql()


# ── 타입 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("data_type", "params", "expected", "pg_name", "typmods"),
    [
        ("varchar", {"length": 20}, "varchar(20)", "varchar", [20]),
        ("char", {"length": 1}, "char(1)", "bpchar", [1]),
        ("text", {}, "text", "text", []),
        ("numeric", {}, "numeric", "numeric", []),
        ("numeric", {"precision": 10}, "numeric(10)", "numeric", [10]),
        ("numeric", {"precision": 10, "scale": 0}, "numeric(10,0)", "numeric", [10, 0]),
        ("numeric", {"precision": 15, "scale": 3}, "numeric(15,3)", "numeric", [15, 3]),
        ("integer", {}, "integer", "int4", []),
        ("bigint", {}, "bigint", "int8", []),
        ("boolean", {}, "boolean", "bool", []),
        ("date", {}, "date", "date", []),
        ("time", {}, "time", "time", []),
        ("time", {"time_precision": 0}, "time(0)", "time", [0]),
        ("timestamp", {"time_precision": 0}, "timestamp(0)", "timestamp", [0]),
        ("timestamp", {}, "timestamp", "timestamp", []),
        ("timestamptz", {"time_precision": 6}, "timestamptz(6)", "timestamptz", [6]),
        ("timestamptz", {}, "timestamptz", "timestamptz", []),
    ],
)
def test_type_text_and_parsed_type_are_kept(
    data_type: str, params: dict[str, int], expected: str, pg_name: str, typmods: list[int]
) -> None:
    """0과 None을 구분하고(time(0)·numeric(10,0)), 세 시각 타입을 서로 바꾸지 않는다."""
    defaults = {"length": None} if data_type not in ("varchar", "char") else {}
    table = _table(
        "T1",
        "wrhus",
        [_key("C1", "wrhus_cd"), _col("C2", "val", data_type, **{**defaults, **params})],
        ("C1",),
    )
    sql = _sql(_model([table]))
    assert f'  "val" {expected},\n' in sql
    (create,) = _statements(sql)
    column = next(e for e in create.tableElts if isinstance(e, ColumnDef) and e.colname == "val")
    assert column.typeName.names[-1].sval == pg_name
    assert [m.val.ival for m in column.typeName.typmods or ()] == typmods


@pytest.mark.parametrize(
    ("data_type", "params", "message"),
    [
        ("varchar", {"length": None}, "양수 length"),
        ("varchar", {"length": 0}, "양수 length"),
        ("char", {"length": -1}, "양수 length"),
        ("text", {"length": 10}, "length를 쓰지 않음"),
        ("integer", {"precision": 10}, "numeric에만"),
        ("varchar", {"length": 10, "scale": 0}, "numeric에만"),
        ("numeric", {"precision": 0}, "precision은 양수"),
        ("numeric", {"precision": -3}, "precision은 양수"),
        ("numeric", {"precision": 1001}, "precision은 1000 이하"),
        ("char", {"length": 10485761}, "length는 10485760 이하"),
        ("varchar", {"length": 10485761}, "length는 10485760 이하"),
        ("numeric", {"scale": 2}, "scale은 0 이상 precision 이하"),
        ("numeric", {"precision": 5, "scale": 6}, "scale은 0 이상 precision 이하"),
        ("numeric", {"precision": 5, "scale": -1}, "scale은 0 이상 precision 이하"),
        ("time", {"time_precision": 7}, "0~6"),
        ("timestamptz", {"time_precision": -1}, "0~6"),
        ("date", {"time_precision": 0}, "시각 타입에만"),
        ("xml", {}, "xml"),
    ],
)
def test_bad_type_parameters_stop_instead_of_being_fixed(
    data_type: str, params: dict[str, Any], message: str
) -> None:
    """계약의 Column은 타입별 매개변수를 검사하지 않아 생성기가 직접 멈춘다."""
    base = _col("C2", "val", "text")
    column = _copy(base, data_type=data_type, **params)
    table = _copy(WAREHOUSE, columns=(WAREHOUSE.columns[0], column))
    with pytest.raises(ValueError, match=re.escape(message)):
        _sql(_model([WAREHOUSE]).model_copy(update={"tables": (table,)}))


# ── 식별자 ───────────────────────────────────────────────────────────


def test_reserved_and_korean_names_are_quoted() -> None:
    table = _table("T1", "order", [_key("C1", "user"), _col("C2", "창고명")], ("C1",))
    sql = _sql(_model([table]))
    assert 'CREATE TABLE "order" (' in sql and '"user" varchar(10) NOT NULL' in sql
    assert '"창고명" varchar(10)' in sql
    assert [type(s) for s in _statements(sql)] == [CreateStmt]


def test_name_at_byte_limit_passes_and_one_byte_over_stops() -> None:
    at_limit = "a" * MAX_BYTES
    table = _table("T1", "wrhus", [_key("C1", at_limit)], ("C1",))
    assert f'"{at_limit}"' in _sql(_model([table]))
    over = _copy(table, columns=(_copy(table.columns[0], physical_name=at_limit + "b"),))
    with pytest.raises(ValueError, match="바이트"):
        _sql(_copy(_model([table]), tables=(over,)))


def test_multibyte_name_is_measured_in_bytes() -> None:
    name = "가" * (MAX_BYTES // 3 + 1)  # 글자 수는 한도 아래지만 바이트는 넘는다
    assert len(name) < MAX_BYTES < len(name.encode("utf-8"))
    table = _table("T1", "wrhus", [_key("C1", name)], ("C1",))
    with pytest.raises(ValueError, match="바이트"):
        _sql(_model([table]))


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "비어 있음"),
        ('wrhus"cd', "큰따옴표"),
        ("wrhus\ncd", "제어 문자"),
        ("Wrhus_cd", "소문자"),
    ],
)
def test_quoting_does_not_replace_name_rules(name: str, message: str) -> None:
    """큰따옴표는 예약어 충돌만 막는다. 대문자·따옴표·제어 문자·빈 이름은 그대로 내보내지 않는다."""
    table = _copy(WAREHOUSE, physical_name=name)
    with pytest.raises(ValueError, match=message):
        _sql(_copy(BASE, tables=(table, RECEIPT)))


# ── 머리말 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("field", ["pack", "pack_version", "rules_version", "lexicon_digest"])
@pytest.mark.parametrize("bad", ["\n", "\r", "\0"])
def test_header_value_with_line_break_or_nul_stops(field: str, bad: str) -> None:
    """`--` 주석 뒤 줄바꿈이 들어가면 다음 줄이 SQL 문장이 된다 (예: SELECT 1;)."""
    model = _copy(BASE, **{field: f"0.1.8{bad}SELECT 1;"})
    with pytest.raises(ValueError, match=f"머리말 값 {field}"):
        _sql(model)


def test_header_injection_would_add_a_statement_without_the_check() -> None:
    """검사가 막는 위험이 실제로 있는지 확인: 줄바꿈이 섞인 주석은 SELECT 문장이 된다."""
    stmts = _statements("-- pack 0.1.8\nSELECT 1;\nCREATE TABLE t (a int);")
    assert len(stmts) == 2


# ── SQL로 내보낼 수 없는 모델 ─────────────────────────────────────────


def _bad_models() -> list[tuple[str, NormalizedModel, str]]:
    no_pk = _copy(WAREHOUSE, primary_key=())
    nullable_pk = _copy(WAREHOUSE, columns=(_col("C1", "wrhus_cd"), WAREHOUSE.columns[1]))
    dup_col = _copy(WAREHOUSE, columns=(WAREHOUSE.columns[0], _col("C2", "wrhus_cd")))
    dup_col_id = _copy(WAREHOUSE, columns=(WAREHOUSE.columns[0], _col("C1", "wrhus_nm")))
    no_cols = _copy(WAREHOUSE, columns=(), primary_key=())
    pk_missing = _copy(WAREHOUSE, primary_key=("C9",))
    unique_missing = _copy(WAREHOUSE, unique_keys=(("C9",),))
    pk_twice = _copy(WAREHOUSE, primary_key=("C1", "C1"))
    dup_table = _copy(RECEIPT, physical_name="wrhus")

    def fk(**kw: Any) -> NormalizedModel:
        return _copy(BASE, foreign_keys=(_copy(RECEIPT_FK, **kw),))

    def tables(*ts: Table) -> NormalizedModel:
        return _copy(BASE, tables=ts)

    return [
        ("empty_pk", tables(no_pk, RECEIPT), "PK가 없음"),
        ("nullable_pk", tables(nullable_pk, RECEIPT), "NULL 허용"),
        ("duplicate_column_name", tables(dup_col, RECEIPT), "칸 물리명이 겹침"),
        ("duplicate_column_id", tables(dup_col_id, RECEIPT), "칸 ID가 겹침"),
        ("no_columns", tables(no_cols, RECEIPT), "칸이 없음"),
        ("pk_unknown_column", tables(pk_missing, RECEIPT), "칸 C9가 테이블에 없음"),
        ("unique_unknown_column", tables(unique_missing, RECEIPT), "칸 C9가 테이블에 없음"),
        ("pk_same_column_twice", tables(pk_twice, RECEIPT), "두 번"),
        (
            "empty_unique",
            tables(_copy(WAREHOUSE, unique_keys=((),)), RECEIPT),
            "칸 묶음이 비어 있음",
        ),
        ("duplicate_table_name", tables(WAREHOUSE, dup_table), "테이블 물리명이 겹침"),
        ("duplicate_table_id", tables(WAREHOUSE, _copy(RECEIPT, id="T1")), "테이블 ID가 겹침"),
        ("fk_unknown_table", fk(parent_table_id="T9"), "테이블이 모델에 없음"),
        ("fk_unknown_column", fk(columns=("C9",)), "칸 C9가 테이블에 없음"),
        ("fk_column_count", fk(columns=("C5", "C3")), "칸 수"),
        ("fk_no_columns", fk(columns=(), parent_columns=()), "칸 수"),
        (
            "fk_parent_not_key",  # 부모 칸 묶음에 PK·UNIQUE가 없으면 PostgreSQL이 FK를 거부한다
            _copy(
                fk(parent_columns=("C2",)),
                tables=(_copy(WAREHOUSE, unique_keys=()), RECEIPT),
            ),
            "PK·UNIQUE가 아님",
        ),
        ("duplicate_fk_id", _copy(BASE, foreign_keys=(RECEIPT_FK, RECEIPT_FK)), "FK ID이 겹침"),
    ]


@pytest.mark.parametrize(
    ("model", "message"),
    [pytest.param(model, message, id=case) for case, model, message in _bad_models()],
)
def test_model_that_cannot_become_sql_stops(model: NormalizedModel, message: str) -> None:
    with pytest.raises(ValueError, match=re.escape(message)):
        _sql(model)


# ── 실제 팩으로 끝까지 ──────────────────────────────────────────────


def _req(req_id: str) -> Requirement:
    return Requirement(
        id=req_id,
        source_ref={"file_format": "csv", "row": 2},
        text=f"{req_id} 문장",
        draft_text=f"{req_id} 문장",
        type="FR",
        analysis_version=1,
    )


def _attr(attr_id: str, name: str, data_type: str = "varchar", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": attr_id,
        "name": name,
        "data_type": data_type,
        "req_ids": ["REQ-01"],
    }
    if data_type == "varchar":
        base["length"] = 10
    if kw.get("is_key"):
        base["nullable"] = False
    return {**base, **kw}


def _rel(rel_id: str, parent: str, child: str, cardinality: str, optional: bool) -> Relationship:
    return Relationship(
        id=rel_id,
        parent=parent,
        child=child,
        cardinality=cardinality,
        optional=optional,
        rationale='"REQ-01 문장" 근거',
        req_ids=["REQ-01"],
    )


def test_inventory_pack_design_to_ddl_end_to_end() -> None:
    """설계 → 정리(실제 재고 사전·naming.yaml) → DDL. 1:N, 선택 자기참조, N:M을 함께 본다.

    미정인 자기참조 접두어(naming.yaml, #11)는 테스트에서 사전 단어 `상위`로 지정했다.
    """
    entities = [
        Entity(
            id="ENT-wh",
            pack="inventory",
            name="창고",
            description="창고 정보",
            attributes=[
                _attr("ATTR-wh-cd", "창고코드", is_key=True),
                _attr("ATTR-wh-nm", "창고명", length=200),
            ],
            req_ids=["REQ-01"],
        ),
        Entity(
            id="ENT-eq",
            pack="inventory",
            name="설비",
            description="설비 정보",
            attributes=[
                _attr("ATTR-eq-cd", "설비코드", is_key=True),
                _attr("ATTR-eq-dt", "거래일시", "timestamp"),
            ],
            req_ids=["REQ-01"],
        ),
    ]
    design = DesignState(
        run_id="run-1",
        requirements=[_req("REQ-01")],
        entities=entities,
        relationships=[
            _rel("REL-01", "ENT-wh", "ENT-eq", "1:N", optional=False),
            _rel("REL-02", "ENT-eq", "ENT-eq", "1:N", optional=True),
            _rel("REL-03", "ENT-wh", "ENT-eq", "N:M", optional=False),
        ],
    )
    rules = replace(load_naming_rules(), self_reference_prefix="상위")
    result = normalize(
        design,
        pack=PackRef("inventory", "0.1.8"),
        lexicon=load_pack_lexicon("inventory"),
        rules=rules,
    )
    assert isinstance(result, Normalized), result
    ddl = generate_ddl(result.model, max_bytes=rules.max_bytes)
    sql = ddl.sql

    assert ddl.lexicon_digest == result.model.lexicon_digest
    stmts = _statements(sql)
    assert [type(s) for s in stmts] == [CreateStmt] * 3 + [AlterTableStmt] * 4
    assert '"dlng_dt" timestamp(0),' in sql  # 팩 도메인의 정밀도 0 보존
    assert 'CREATE TABLE "wrhus_eqpm" (' in sql  # N:M 연결 테이블
    assert 'PRIMARY KEY ("wrhus_cd", "eqpm_cd")' in sql
    assert '"up_eqpm_cd" varchar(10),' in sql  # 선택 자기참조 FK는 NULL 허용
    assert 'ADD FOREIGN KEY ("up_eqpm_cd") REFERENCES "eqpm" ("eqpm_cd");' in sql
    assert 'ALTER TABLE "eqpm" ADD FOREIGN KEY ("wrhus_cd") REFERENCES "wrhus" ("wrhus_cd");' in sql


@pytest.mark.parametrize("max_bytes", [0, -1, 64])
def test_max_bytes_outside_postgres_limit_stops(max_bytes: int) -> None:
    """팩 한도가 PostgreSQL 한도(63)를 넘으면 다른 이름이 같은 이름으로 잘린다."""
    with pytest.raises(ValueError, match="max_bytes"):
        generate_ddl(BASE, max_bytes=max_bytes)


def test_names_that_postgres_would_truncate_to_the_same_name_are_not_generated() -> None:
    """64바이트 두 이름은 PostgreSQL에서 같은 63바이트 이름이 된다. 한도 검사로 생성 전에 막는다."""
    x, y = "a" * 63 + "x", "a" * 63 + "y"
    (create,) = _statements(f'CREATE TABLE t ("{x}" int, "{y}" int);')
    assert {e.colname for e in create.tableElts} == {"a" * 63}  # 파서가 잘라 같은 이름이 됨
    table = _table("T1", "wrhus", [_key("C1", x), _col("C2", y)], ("C1",))
    with pytest.raises(ValueError, match="max_bytes"):
        generate_ddl(_model([table]), max_bytes=64)
    with pytest.raises(ValueError, match="바이트"):
        _sql(_model([table]))


def test_maintenance_pack_design_to_ddl_end_to_end() -> None:
    """설계 → 정리(실제 설비 팩 사전·naming.yaml) → DDL → 파싱. 1:N 하나."""
    entities = [
        Entity(
            id="ENT-eq",
            pack="maintenance",
            name="설비",
            description="설비 정보",
            attributes=[
                _attr("ATTR-eq-cd", "설비코드", is_key=True),
                _attr("ATTR-eq-nm", "설비명", length=200),
            ],
            req_ids=["REQ-01"],
        ),
        Entity(
            id="ENT-rc",
            pack="maintenance",
            name="고장접수",
            description="고장 접수 정보",
            attributes=[
                _attr("ATTR-rc-no", "접수번호", is_key=True),
                _attr("ATTR-rc-dt", "접수일시", "timestamp"),
            ],
            req_ids=["REQ-01"],
        ),
    ]
    design = DesignState(
        run_id="run-1",
        requirements=[_req("REQ-01")],
        entities=entities,
        relationships=[_rel("REL-01", "ENT-eq", "ENT-rc", "1:N", optional=False)],
    )
    rules = load_naming_rules()
    result = normalize(
        design,
        pack=PackRef("maintenance", "test"),
        lexicon=load_pack_lexicon("maintenance"),
        rules=rules,
    )
    assert isinstance(result, Normalized), result
    sql = generate_ddl(result.model, max_bytes=rules.max_bytes).sql
    assert [type(s) for s in _statements(sql)] == [CreateStmt, CreateStmt, AlterTableStmt]
    assert '"rcpt_dt" timestamp(0),' in sql
    assert (
        'ALTER TABLE "bkdn_rcpt" ADD FOREIGN KEY ("eqpm_cd") REFERENCES "eqpm" ("eqpm_cd");'
    ) in sql


@pytest.mark.parametrize(
    ("data_type", "params", "expected"),
    [
        ("numeric", {"precision": 1000}, "numeric(1000)"),
        ("numeric", {"precision": 1000, "scale": 1000}, "numeric(1000,1000)"),
        ("char", {"length": 10485760}, "char(10485760)"),
        ("varchar", {"length": 10485760}, "varchar(10485760)"),
    ],
)
def test_type_parameter_at_postgres_upper_bound_passes(
    data_type: str, params: dict[str, int], expected: str
) -> None:
    """PostgreSQL 18 상한값은 통과한다. 상한+1은 위 거절 테스트에서 멈춘다 (줄이지 않음)."""
    defaults = {"length": None} if data_type == "numeric" else {}
    column = _col("C2", "val", data_type, **{**defaults, **params})
    table = _table("T1", "wrhus", [_key("C1", "wrhus_cd"), column], ("C1",))
    sql = _sql(_model([table]))
    assert f'  "val" {expected},\n' in sql
    assert [type(s) for s in _statements(sql)] == [CreateStmt]


def test_header_does_not_claim_a_validation_state() -> None:
    """파일은 검증 전에 해시가 정해져 검증 뒤에 고칠 수 없다. 상태는 API·승인 기록에 둔다."""
    assert "validation" not in _sql().splitlines()[0]
    assert DDL_GENERATOR_VERSION == "ddl-v1"
