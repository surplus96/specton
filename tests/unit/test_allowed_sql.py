"""SQL 검증 앞 두 단계 (#15): 파싱 → 허용 SQL 검사.

DB에 접속하지 않는다. 정상 SQL도 격리 DB 단계가 남아 전체 상태는 `unverified`다.
"""

import ast as pyast
import hashlib
from pathlib import Path

import pytest

from specton.contracts.base import SqlType
from specton.validate import allowed_sql
from specton.validate.allowed_sql import (
    POLICY_VERSION,
    STAGES,
    TARGET,
    VALIDATOR_VERSION,
    SqlValidation,
    StageResult,
    build_result,
    check_allowed_sql,
    overall_state,
)

ROOT = Path(__file__).resolve().parents[2]

# DDL 생성기(#165) 출력과 같은 모양: 머리말 주석, 큰따옴표 이름, 표 제약, 복합·자기참조 FK
HEADER = (
    "-- postgresql 18 / pack inventory 0.1.8 / rules normalize-v0 / lexicon abc"
    " / generator ddl-v0 / validation unverified\n"
)
GENERATED = (
    HEADER
    + """\

CREATE TABLE "wrhus" (
  "wrhus_cd" varchar(10) NOT NULL,
  "wrhus_nm" varchar(200),
  PRIMARY KEY ("wrhus_cd"),
  UNIQUE ("wrhus_nm")
);

CREATE TABLE "order" (
  "bzmn_no" char(10) NOT NULL,
  "brnch_sn" integer NOT NULL,
  "up_bzmn_no" char(10),
  "up_brnch_sn" integer,
  "qty" numeric(15,3),
  "amt" numeric,
  "rate" numeric(10,0),
  "big" bigint,
  "flag" boolean,
  "memo" text,
  "ymd" date,
  "tm" time(0),
  "dt" timestamp(0),
  "tz" timestamptz(6),
  "wrhus_cd" varchar(10) NOT NULL,
  PRIMARY KEY ("bzmn_no", "brnch_sn")
);

ALTER TABLE "order" ADD FOREIGN KEY ("wrhus_cd") REFERENCES "wrhus" ("wrhus_cd");

ALTER TABLE "order" ADD FOREIGN KEY ("up_bzmn_no", "up_brnch_sn")
  REFERENCES "order" ("bzmn_no", "brnch_sn");
"""
)


def _check(sql: str | bytes) -> SqlValidation:
    return check_allowed_sql(sql.encode("utf-8") if isinstance(sql, str) else sql)


def _stage(result: SqlValidation, name: str) -> StageResult:
    return next(s for s in result.stages if s.stage == name)


def _not_allowed(sql: str) -> list[str]:
    result = _check(sql)
    assert result.state == "failed", result
    stage = _stage(result, "allowed_sql")
    assert stage.state == "failed"
    assert all(p.kind == "not_allowed" for p in stage.problems)
    return [p.detail for p in stage.problems]


# ── 결과 모양 ─────────────────────────────────────────────────────────


def test_generated_ddl_passes_first_two_stages_and_stays_unverified() -> None:
    result = _check(GENERATED)
    assert [(s.stage, s.state) for s in result.stages] == [
        ("parse", "passed"),
        ("allowed_sql", "passed"),
        ("sandbox_execute", "not_run"),
        ("rollback", "not_run"),
        ("residual_check", "not_run"),
    ]
    assert result.state == "unverified"  # 격리 DB 전에는 passed가 아니다


def test_result_carries_hash_of_all_bytes_and_versions() -> None:
    data = GENERATED.encode("utf-8")
    result = check_allowed_sql(data)
    assert result.sql_sha256 == hashlib.sha256(data).hexdigest()
    assert check_allowed_sql(data + b" ").sql_sha256 != result.sql_sha256
    assert (result.validator_version, result.policy_version, result.target) == (
        VALIDATOR_VERSION,
        POLICY_VERSION,
        TARGET,
    )
    assert result == check_allowed_sql(data)  # 같은 입력 → 같은 결과


def test_stages_are_always_five_in_fixed_order() -> None:
    for sql in (GENERATED, "SELECT 1;", "CREATE TABLE (", ""):
        assert tuple(s.stage for s in _check(sql).stages) == STAGES


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        (["passed"] * 5, "passed"),
        (["passed", "passed", "not_run", "not_run", "not_run"], "unverified"),
        (["passed", "failed", "not_run", "not_run", "not_run"], "failed"),
        (["passed", "error", "not_run", "not_run", "not_run"], "error"),
        # SQL 결함 뒤 정리까지 실패: 전체는 error, 결함 단계는 failed로 남는다 (#167 검토)
        (["passed", "passed", "failed", "error", "not_run"], "error"),
        (["passed", "passed", "error", "failed", "not_run"], "error"),
    ],
)
def test_overall_state_puts_error_first_then_failed_then_unverified(
    states: list[str], expected: str
) -> None:
    stages = [
        StageResult(stage=name, state=state)  # type: ignore[arg-type]
        for name, state in zip(STAGES, states, strict=True)
    ]
    assert overall_state(stages) == expected


def _passed(name: str) -> StageResult:
    return StageResult(stage=name, state="passed")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "names",
    [
        [],  # 빈 목록이 passed가 되면 안 된다
        ["parse", "allowed_sql"],  # 일부 단계만
        [*STAGES, "parse"],  # 중복
        list(reversed(STAGES)),  # 순서가 다름
    ],
    ids=["empty", "partial", "duplicate", "reordered"],
)
def test_overall_state_needs_all_five_stages_once_in_order(names: list[str]) -> None:
    with pytest.raises(ValueError, match="5단계"):
        overall_state([_passed(n) for n in names])


def test_duplicate_stage_in_build_result_is_rejected_not_overwritten() -> None:
    """파싱 실패 뒤 파싱 성공을 넣어 실패를 덮어쓰면 안 된다 (검토에서 재현)."""
    failed = StageResult(stage="parse", state="failed")
    with pytest.raises(ValueError, match="두 번"):
        build_result(b"x", [failed, _passed("parse")])
    with pytest.raises(ValueError, match="두 번"):
        build_result(b"x", [_passed(n) for n in STAGES] + [failed])


def test_build_result_with_no_stage_run_is_unverified() -> None:
    assert build_result(b"x", []).state == "unverified"


def test_failed_and_error_together_keep_the_failed_stage() -> None:
    failed = StageResult(stage="sandbox_execute", state="failed")
    error = StageResult(stage="rollback", state="error")
    result = build_result(b"x", [StageResult(stage="parse", state="passed"), failed, error])
    assert result.state == "error"
    assert _stage(result, "sandbox_execute") == failed


def test_unknown_stage_name_stops() -> None:
    with pytest.raises(ValueError, match="모르는 단계"):
        build_result(b"x", [StageResult.model_construct(stage="deploy", state="passed")])


# ── 파싱 단계 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (b"", "empty"),
        (b"-- comment only\n", "empty"),
        (b"   \n", "empty"),
        (b"\xff\xfeCREATE", "not_utf8"),
        (b"CREATE TABLE (", "parse_error"),
    ],
)
def test_parse_failures_stop_before_allowed_check(data: bytes, kind: str) -> None:
    result = check_allowed_sql(data)
    assert result.state == "failed"
    parse = _stage(result, "parse")
    assert (parse.state, [p.kind for p in parse.problems]) == ("failed", [kind])
    assert _stage(result, "allowed_sql").state == "not_run"


@pytest.mark.parametrize(
    "data",
    [
        b"CREATE TABLE t (x integer);\x00COMMIT;",
        b"\x00CREATE TABLE t (x integer);",
        b"CREATE TABLE t (x integer);\x00",
        b'CREATE TABLE "t\x00" (x integer);',
    ],
)
def test_nul_byte_is_rejected_before_parsing(data: bytes) -> None:
    """pglast는 NUL 뒤를 읽지 않는다. 앞부분만 검사하고 통과시키면 안 된다 (#167 검토)."""
    result = check_allowed_sql(data)
    assert result.state == "failed"
    assert [p.kind for p in _stage(result, "parse").problems] == ["nul_byte"]
    assert result.sql_sha256 == hashlib.sha256(data).hexdigest()  # NUL 포함 전체 바이트


def test_parser_crash_is_error_not_sql_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(allowed_sql, "parse_sql", broken)
    result = _check(GENERATED)
    assert result.state == "error"
    assert _stage(result, "parse").state == "error"
    assert [p.kind for p in _stage(result, "parse").problems] == ["internal"]


def test_checker_crash_is_error_not_sql_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(allowed_sql, "_statement_problems", broken)
    result = _check(GENERATED)
    assert (result.state, _stage(result, "allowed_sql").state) == ("error", "error")


# ── 허용 밖 문장 ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "COMMIT;",
        "BEGIN;",
        "ROLLBACK;",
        "SAVEPOINT s;",
        "SET search_path = public;",
        "RESET ALL;",
        "DO $$ BEGIN PERFORM 1; END $$;",
        "COPY t FROM PROGRAM 'id';",
        "CREATE EXTENSION dblink;",
        "CREATE FUNCTION f() RETURNS int AS 'select 1' LANGUAGE sql;",
        "CREATE TYPE text AS (a int);",
        "CREATE SCHEMA s;",
        "CREATE INDEX i ON t (a);",
        "COMMENT ON TABLE t IS 'x';",
        "DROP TABLE t;",
        "INSERT INTO t VALUES (1);",
        "SELECT 1;",
        "GRANT ALL ON t TO PUBLIC;",
        "CREATE TABLE t AS SELECT 1;",
        "SELECT 1 INTO t;",
        "CREATE VIEW v AS SELECT 1;",
    ],
)
def test_statements_outside_the_list_are_rejected(sql: str) -> None:
    [detail] = _not_allowed(sql)
    assert "허용하지 않는 문장" in detail


def test_every_bad_statement_is_reported_with_its_number() -> None:
    sql = 'CREATE TABLE "a" ("x" integer);\nCOMMIT;\nCREATE TABLE "b" ("y" integer);\nSELECT 1;'
    stage = _stage(_check(sql), "allowed_sql")
    assert [(p.statement, p.detail.split(":")[0]) for p in stage.problems] == [
        (1, "허용하지 않는 문장"),
        (3, "허용하지 않는 문장"),
    ]


def test_line_break_after_header_comment_makes_a_statement_that_is_rejected() -> None:
    sql = "-- pack 0.1.8\nSELECT 1;\n" + 'CREATE TABLE "t" ("a" integer);'
    stage = _stage(_check(sql), "allowed_sql")
    assert [p.statement for p in stage.problems] == [0]


def test_dangerous_words_inside_strings_or_identifiers_are_judged_by_the_tree() -> None:
    """판단은 파싱 결과로 한다. 이름 안의 글자는 문장이 아니다."""
    assert _check('CREATE TABLE "commit; drop table x" ("a" integer);').state == "unverified"


# ── CREATE TABLE ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sql", "fragment"),
    [
        ("CREATE TEMP TABLE t (a integer);", "일반 테이블만"),
        ("CREATE UNLOGGED TABLE t (a integer);", "일반 테이블만"),
        ("CREATE TABLE IF NOT EXISTS t (a integer);", "if_not_exists"),
        ("CREATE TABLE t (a integer) INHERITS (p);", "inhRelations"),
        ("CREATE TABLE t (a integer) PARTITION BY RANGE (a);", "partspec"),
        ("CREATE TABLE t PARTITION OF p FOR VALUES IN (1);", "partbound"),
        ("CREATE TABLE t (LIKE p);", "TableLikeClause"),
        ("CREATE TABLE t (a integer) WITH (fillfactor=70);", "options"),
        ("CREATE TABLE t (a integer) TABLESPACE x;", "tablespacename"),
        ("CREATE TEMP TABLE t (a integer) ON COMMIT DROP;", "oncommit"),
        ("CREATE TABLE t (a integer) USING heap;", "accessMethod"),
        ("CREATE TABLE t OF some_type;", "ofTypename"),
        ("CREATE TABLE public.t (a integer);", "스키마"),
        ("CREATE TABLE pg_catalog.t (a integer);", "스키마"),
        ("CREATE TABLE t ();", "칸이 없음"),
    ],
)
def test_create_table_options_are_rejected(sql: str, fragment: str) -> None:
    assert any(fragment in d for d in _not_allowed(sql))


@pytest.mark.parametrize(
    ("column", "fragment"),
    [
        ("a integer DEFAULT 1", "허용하지 않는 제약"),
        ("a timestamp DEFAULT now()", "허용하지 않는 제약"),
        ("a integer CHECK (a > 0)", "허용하지 않는 제약"),
        ("a integer GENERATED ALWAYS AS (1) STORED", "허용하지 않는 제약"),
        ("a integer GENERATED ALWAYS AS IDENTITY", "허용하지 않는 제약"),
        ('a text COLLATE "C"', "collClause"),
        ("a text STORAGE external", "storage"),
        ("a text COMPRESSION pglz", "compression"),
        ("a integer NOT NULL NO INHERIT", "is_no_inherit"),
    ],
)
def test_column_extras_are_rejected(column: str, fragment: str) -> None:
    assert any(fragment in d for d in _not_allowed(f"CREATE TABLE t ({column});"))


# ── 타입 ─────────────────────────────────────────────────────────────


def test_type_table_covers_exactly_the_allowed_sql_types() -> None:
    assert set(allowed_sql._TYPE_NAMES) == set(SqlType)


@pytest.mark.parametrize(
    "type_text",
    [
        "char(1)",
        "varchar(20)",
        "text",
        "numeric",
        "numeric(10)",
        "numeric(10,0)",
        "integer",
        "int",
        "bigint",
        "boolean",
        "date",
        "time",
        "time(0)",
        "timestamp",
        "timestamp(6)",
        "timestamptz",
        "timestamptz(6)",
    ],
)
def test_allowed_types_pass_even_though_the_parser_adds_pg_catalog(type_text: str) -> None:
    assert _check(f"CREATE TABLE t (a {type_text});").state == "unverified"


@pytest.mark.parametrize(
    "type_text",
    [
        "json",
        "serial",
        "uuid",
        "real",
        "int4[]",
        "integer[3]",
        "public.int4",
        "myschema.varchar(10)",
        "pg_catalog.json",
        "pg_catalog.text",
        '"int4"',
        "varchar",
        "char(1, 2)",
        "numeric(1,2,3)",
        "timestamp(1,2)",
        "integer(5)",
        "interval",
        "t.a%TYPE",
        "SETOF integer",
    ],
)
def test_other_types_and_shapes_are_rejected(type_text: str) -> None:
    result = _check(f"CREATE TABLE t (a {type_text});")
    assert result.state == "failed", type_text


# ── 제약 ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE t (a integer, PRIMARY KEY (a) WITH (fillfactor=70));",
        "CREATE TABLE t (a integer PRIMARY KEY WITH (fillfactor=70));",
        "CREATE TABLE t (a integer, UNIQUE (a) WITH (fillfactor=70));",
        "CREATE TABLE t (a integer UNIQUE WITH (fillfactor=70));",
        "CREATE TABLE t (a integer, UNIQUE (a) USING INDEX TABLESPACE x);",
        "CREATE TABLE t (a integer PRIMARY KEY USING INDEX TABLESPACE x);",
        "CREATE TABLE t (a integer, b integer, UNIQUE (a) INCLUDE (b));",
        "CREATE TABLE t (a integer, UNIQUE NULLS NOT DISTINCT (a));",
        "CREATE TABLE t (a integer, UNIQUE (a) DEFERRABLE);",
        "CREATE TABLE t (a integer UNIQUE DEFERRABLE INITIALLY DEFERRED);",
        "CREATE TABLE t (a integer, CHECK (a > 0));",
        "CREATE TABLE t (a integer, EXCLUDE USING gist (a WITH =));",
    ],
)
def test_constraint_options_are_rejected_on_table_and_column(sql: str) -> None:
    _not_allowed(sql)


def test_constraint_names_are_allowed() -> None:
    sql = (
        "CREATE TABLE p (a integer, CONSTRAINT p_pk PRIMARY KEY (a));\n"
        "CREATE TABLE c (a integer CONSTRAINT c_a_nn NOT NULL, CONSTRAINT c_uq UNIQUE (a));\n"
        "ALTER TABLE c ADD CONSTRAINT c_fk FOREIGN KEY (a) REFERENCES p (a);"
    )
    assert _check(sql).state == "unverified"


def test_inline_references_and_null_are_allowed() -> None:
    sql = "CREATE TABLE c (a integer NULL REFERENCES p (a), b integer REFERENCES p);"
    assert _check(sql).state == "unverified"


# ── ALTER TABLE ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sql", "fragment"),
    [
        ("ALTER TABLE t DROP COLUMN a;", "하위 명령"),
        ("ALTER TABLE t ADD COLUMN a integer;", "하위 명령"),
        ("ALTER TABLE t OWNER TO x;", "하위 명령"),
        ("ALTER TABLE t ENABLE TRIGGER ALL;", "하위 명령"),
        ("ALTER TABLE t SET SCHEMA s;", "허용하지 않는 문장"),
        ("ALTER TABLE t ADD UNIQUE (a);", "FOREIGN KEY 추가만"),
        ("ALTER TABLE t ADD PRIMARY KEY (a);", "FOREIGN KEY 추가만"),
        (
            "ALTER TABLE t ADD FOREIGN KEY (a) REFERENCES p (a),"
            " ADD FOREIGN KEY (b) REFERENCES p (b);",
            "하나만",
        ),
        ("ALTER TABLE ONLY t ADD FOREIGN KEY (a) REFERENCES p (a);", "ONLY"),
        ("ALTER TABLE IF EXISTS t ADD FOREIGN KEY (a) REFERENCES p (a);", "missing_ok"),
        ("ALTER TABLE public.t ADD FOREIGN KEY (a) REFERENCES p (a);", "스키마"),
        ("ALTER TABLE t ADD FOREIGN KEY (a) REFERENCES public.p (a);", "스키마"),
        ("ALTER TABLE t ADD FOREIGN KEY (a) REFERENCES p (a) ON DELETE CASCADE;", "NO ACTION"),
        ("ALTER TABLE t ADD FOREIGN KEY (a) REFERENCES p (a) ON UPDATE SET NULL;", "NO ACTION"),
        ("ALTER TABLE t ADD FOREIGN KEY (a) REFERENCES p (a) MATCH FULL;", "SIMPLE"),
        ("ALTER TABLE t ADD FOREIGN KEY (a) REFERENCES p (a) NOT VALID;", "NOT VALID"),
        ("ALTER TABLE t ADD FOREIGN KEY (a) REFERENCES p (a) DEFERRABLE;", "deferrable"),
        ("ALTER TABLE t ADD FOREIGN KEY (a) REFERENCES p (a) NOT ENFORCED;", "NOT ENFORCED"),
    ],
)
def test_alter_table_other_than_plain_foreign_key_is_rejected(sql: str, fragment: str) -> None:
    details = _not_allowed(sql)
    assert any(fragment in d for d in details), details


def test_column_level_references_options_are_rejected() -> None:
    _not_allowed("CREATE TABLE c (a integer REFERENCES p (a) ON DELETE CASCADE);")
    _not_allowed("CREATE TABLE c (a integer REFERENCES public.p (a));")


# ── 경계 ─────────────────────────────────────────────────────────────


def test_validate_does_not_import_llm_or_nodes() -> None:
    """검증기는 LLM client를 import하지 않는다 (CLAUDE.md)."""
    for path in (ROOT / "specton/validate").glob("*.py"):
        tree = pyast.parse(path.read_text(encoding="utf-8"))
        for node in pyast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, pyast.Import)
                else [node.module or ""]
                if isinstance(node, pyast.ImportFrom)
                else []
            )
            for name in names:
                assert not name.startswith(("specton.llm", "specton.nodes", "openai")), path
