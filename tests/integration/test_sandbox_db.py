"""격리 DB 실행·롤백·잔여 확인 (#15, TC-F11). 실제 PostgreSQL 18 sandbox DB에서 실행한다.

`docker compose up -d db` 뒤 `uv run pytest -m db tests/integration/test_sandbox_db.py`로 돌린다.
이 파일은 앱 DB용 `pool` fixture를 쓰지 않고, sandbox 계정으로 연결한다. 테스트가 직접 만든
객체(기준 표시용 스키마)만 지운다.
"""

import threading
from collections.abc import Iterator
from dataclasses import replace
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql as pgsql

from specton.codegen.ddl import generate_ddl
from specton.codegen.model import Normalized
from specton.codegen.naming import load_naming_rules, load_pack_lexicon
from specton.codegen.normalize import PackRef, normalize
from specton.config import Settings
from specton.contracts import DesignState, Entity, Relationship, Requirement
from specton.validate.allowed_sql import SqlValidation
from specton.validate.sandbox import SCHEMA_PREFIX, SandboxLimits, validate_sql

pytestmark = pytest.mark.db

# Windows의 Docker Desktop에서는 localhost가 IPv6(::1)를 먼저 시도해 연결마다 connect_timeout만큼
# 기다린다(이 PC에서 5초). 시험에서는 같은 DB를 IPv4 주소로 연결한다. 검증기 동작은 같다.
_BASE = Settings(_env_file=None)
SETTINGS = Settings(
    _env_file=None,
    sandbox_database_url=str(_BASE.sandbox_database_url).replace("@localhost:", "@127.0.0.1:"),
    app_database_url=str(_BASE.app_database_url).replace("@localhost:", "@127.0.0.1:"),
)
URL = str(SETTINGS.sandbox_database_url)


@pytest.fixture(autouse=True)
def sandbox_available() -> None:
    try:
        psycopg.connect(URL, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("로컬 sandbox DB가 없습니다 (docker compose up -d db)")


@pytest.fixture
def sentinel() -> Iterator[str]:
    """검증 밖에 있는 기존 객체. 검증이 이것을 건드리거나 이름이 이리로 빠지지 않아야 한다."""
    schema = f"test_sentinel_{uuid4().hex[:12]}"
    with psycopg.connect(URL, autocommit=True, connect_timeout=5) as conn:
        conn.execute(pgsql.SQL("CREATE SCHEMA {}").format(pgsql.Identifier(schema)))
        conn.execute(
            pgsql.SQL('CREATE TABLE {}.p ("a" integer PRIMARY KEY)').format(
                pgsql.Identifier(schema)
            )
        )
    try:
        yield schema
    finally:
        with psycopg.connect(URL, autocommit=True, connect_timeout=5) as conn:
            conn.execute(pgsql.SQL("DROP SCHEMA {} CASCADE").format(pgsql.Identifier(schema)))


def _validate(sql: str, **limits: float) -> SqlValidation:
    return validate_sql(sql.encode("utf-8"), settings=SETTINGS, limits=SandboxLimits(**limits))


def _states(result: SqlValidation) -> dict[str, str]:
    return {s.stage: s.state for s in result.stages}


def _check_schemas() -> list[str]:
    with psycopg.connect(URL, autocommit=True, connect_timeout=5) as conn:
        rows = conn.execute(
            "SELECT nspname FROM pg_namespace WHERE starts_with(nspname, %s)", (SCHEMA_PREFIX,)
        ).fetchall()
    return [r[0] for r in rows]


# ── 생성기 출력으로 끝까지 ───────────────────────────────────────────


def _req() -> Requirement:
    return Requirement(
        id="REQ-01",
        source_ref={"file_format": "csv", "row": 2},
        text="문장",
        draft_text="문장",
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


def _rel(rel_id: str, parent: str, child: str, cardinality: str, **kw: Any) -> Relationship:
    return Relationship(
        id=rel_id,
        parent=parent,
        child=child,
        cardinality=cardinality,
        optional=kw.pop("optional", False),
        rationale='"문장" 근거',
        req_ids=["REQ-01"],
        **kw,
    )


def _inventory_ddl() -> str:
    """실제 재고 사전으로 정리한 설계의 DDL. 1:N, 선택 자기참조, N:M을 함께 담는다.

    미정인 자기참조 접두어는 테스트에서 사전 단어 `상위`로 지정한다(naming.yaml에 값이 없는 경우).
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
        requirements=[_req()],
        entities=entities,
        relationships=[
            _rel("REL-01", "ENT-wh", "ENT-eq", "1:N"),
            _rel("REL-02", "ENT-eq", "ENT-eq", "1:N", optional=True),
            _rel("REL-03", "ENT-wh", "ENT-eq", "N:M"),
        ],
    )
    rules = load_naming_rules()
    if rules.self_reference_prefix is None:
        rules = replace(rules, self_reference_prefix="상위")
    result = normalize(
        design,
        pack=PackRef("inventory", "test"),
        lexicon=load_pack_lexicon("inventory"),
        rules=rules,
    )
    assert isinstance(result, Normalized), result
    return generate_ddl(result.model, max_bytes=rules.max_bytes).sql


def test_generated_ddl_passes_all_five_stages_and_leaves_nothing() -> None:
    sql = _inventory_ddl()
    assert "ADD FOREIGN KEY" in sql and "timestamp(0)" in sql  # 복합 구조가 실제로 들어감

    result = _validate(sql)

    assert result.state == "passed", result
    assert set(_states(result).values()) == {"passed"}
    assert _check_schemas() == []


def test_composite_keys_unique_and_generator_types_run() -> None:
    sql = """
CREATE TABLE "bcnc" (
  "bzmn_no" char(10) NOT NULL,
  "brnch_sn" integer NOT NULL,
  "qty" numeric(10,0),
  "amt" numeric(15,3),
  "rate" numeric,
  "tm" time(0),
  "dt" timestamp(0),
  "tz" timestamptz(6),
  "memo" text,
  "ymd" date,
  "flag" boolean,
  "big" bigint,
  PRIMARY KEY ("bzmn_no", "brnch_sn"),
  UNIQUE ("memo")
);
CREATE TABLE "wrhsg" (
  "wrhsg_no" varchar(20) NOT NULL,
  "bzmn_no" char(10) NOT NULL,
  "brnch_sn" integer NOT NULL,
  PRIMARY KEY ("wrhsg_no")
);
ALTER TABLE "wrhsg" ADD FOREIGN KEY ("bzmn_no", "brnch_sn")
  REFERENCES "bcnc" ("bzmn_no", "brnch_sn");
"""
    result = _validate(sql)
    assert result.state == "passed", result


# ── 실행 중 SQL 결함 ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sql", "statement", "sqlstate"),
    [
        (  # 부모 칸에 UNIQUE·PK가 없음
            'CREATE TABLE "p" ("a" integer PRIMARY KEY, "n" integer);\n'
            'CREATE TABLE "c" ("n" integer);\n'
            'ALTER TABLE "c" ADD FOREIGN KEY ("n") REFERENCES "p" ("n");',
            2,
            "42830",
        ),
        (  # 없는 부모 테이블
            'CREATE TABLE "c" ("a" integer);\n'
            'ALTER TABLE "c" ADD FOREIGN KEY ("a") REFERENCES "p" ("a");',
            1,
            "42P01",
        ),
        (  # 타입이 다른 FK
            'CREATE TABLE "p" ("a" integer PRIMARY KEY);\n'
            'CREATE TABLE "c" ("a" date);\n'
            'ALTER TABLE "c" ADD FOREIGN KEY ("a") REFERENCES "p" ("a");',
            2,
            "42804",
        ),
        (  # 파서는 통과하지만 서버가 거절하는 타입 매개변수
            'CREATE TABLE "t" ("a" numeric(1001));',
            0,
            "22023",
        ),
        (  # 같은 테이블 두 번
            'CREATE TABLE "t" ("a" integer);\nCREATE TABLE "t" ("a" integer);',
            1,
            "42P07",
        ),
    ],
    ids=["fk_not_unique", "missing_parent", "fk_type_mismatch", "numeric_limit", "duplicate"],
)
def test_sql_defect_is_failed_with_its_statement_and_earlier_objects_are_gone(
    sql: str, statement: int, sqlstate: str
) -> None:
    result = _validate(sql)

    assert result.state == "failed", result
    execute = next(s for s in result.stages if s.stage == "sandbox_execute")
    [problem] = execute.problems
    assert (problem.kind, problem.statement, problem.sqlstate) == (
        "execution_error",
        statement,
        sqlstate,
    )
    # 앞에서 만든 테이블까지 롤백되고 검증 스키마도 남지 않는다
    assert (_states(result)["rollback"], _states(result)["residual_check"]) == ("passed", "passed")
    assert _check_schemas() == []


# ── 격리 ─────────────────────────────────────────────────────────────


@pytest.fixture
def public_parent() -> Iterator[str]:
    """기본 검색 경로에 있는 public에 둔 부모 표. 검증 SQL이 이 표를 찾으면 격리가 깨진 것이다."""
    name = f"p_{uuid4().hex[:12]}"
    with psycopg.connect(URL, autocommit=True, connect_timeout=5) as conn:
        conn.execute(
            pgsql.SQL('CREATE TABLE public.{} ("a" integer PRIMARY KEY)').format(
                pgsql.Identifier(name)
            )
        )
    try:
        yield name
    finally:
        with psycopg.connect(URL, autocommit=True, connect_timeout=5) as conn:
            conn.execute(pgsql.SQL("DROP TABLE public.{}").format(pgsql.Identifier(name)))


def test_names_do_not_fall_through_to_public(public_parent: str) -> None:
    """public에 같은 이름 표가 있어도 검증 SQL은 그 표를 찾지 못한다(검색 경로에 public 없음)."""
    result = _validate(
        'CREATE TABLE "c" ("a" integer);\n'
        f'ALTER TABLE "c" ADD FOREIGN KEY ("a") REFERENCES "{public_parent}" ("a");'
    )
    execute = next(s for s in result.stages if s.stage == "sandbox_execute")
    assert (result.state, execute.problems[0].sqlstate) == ("failed", "42P01")


def test_names_do_not_fall_through_to_other_schemas(sentinel: str) -> None:
    """다른 스키마에 같은 이름 표(p)가 있어도 검증 SQL은 그 표를 찾지 못한다."""
    result = _validate(
        'CREATE TABLE "c" ("a" integer);\n'
        'ALTER TABLE "c" ADD FOREIGN KEY ("a") REFERENCES "p" ("a");'
    )
    execute = next(s for s in result.stages if s.stage == "sandbox_execute")
    assert (result.state, execute.problems[0].sqlstate) == ("failed", "42P01")


def test_existing_objects_survive_success_and_failure(sentinel: str) -> None:
    _validate('CREATE TABLE "p" ("a" integer PRIMARY KEY);')
    _validate('CREATE TABLE "t" ("a" numeric(1001));')
    with psycopg.connect(URL, autocommit=True, connect_timeout=5) as conn:
        exists = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (f"{sentinel}.p",)).fetchone()
    assert exists == (True,)


@pytest.mark.parametrize("where", ["sentinel", "public"])
def test_builtin_type_names_resolve_even_with_same_named_types_elsewhere(
    sentinel: str, where: str
) -> None:
    """다른 스키마(기본 검색 경로의 public 포함)에 text·date·timestamptz라는 타입이 있어도
    검증은 내장 타입으로 실행된다. 같은 이름 타입이 정수 도메인이라 잘못 해석되면 FK·타입이 깨진다.
    """
    schema = sentinel if where == "sentinel" else "public"
    names = ("text", "date", "timestamptz")
    with psycopg.connect(URL, autocommit=True, connect_timeout=5) as conn:
        for name in names:
            conn.execute(
                pgsql.SQL("CREATE DOMAIN {}.{} AS integer CHECK (VALUE > 0)").format(
                    pgsql.Identifier(schema), pgsql.Identifier(name)
                )
            )
    try:
        _run_builtin_type_check()
    finally:
        if where == "public":
            with psycopg.connect(URL, autocommit=True, connect_timeout=5) as conn:
                for name in names:
                    conn.execute(pgsql.SQL("DROP DOMAIN public.{}").format(pgsql.Identifier(name)))


def _run_builtin_type_check() -> None:
    result = _validate(
        'CREATE TABLE "p" ("t" text PRIMARY KEY, "d" date, "z" timestamptz);\n'
        'CREATE TABLE "c" ("t" text);\n'
        'ALTER TABLE "c" ADD FOREIGN KEY ("t") REFERENCES "p" ("t");'
    )
    assert result.state == "passed", result


def test_same_sql_twice_and_concurrent_runs_do_not_interfere() -> None:
    sql = _inventory_ddl()
    results: list[SqlValidation] = []

    def run() -> None:
        results.append(_validate(sql))

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    results.append(_validate(sql))  # 같은 SQL 한 번 더

    assert [r.state for r in results] == ["passed"] * 4
    assert _check_schemas() == []


# ── 시간 예산 ─────────────────────────────────────────────────────────


def test_tiny_budget_is_budget_exceeded_and_still_cleaned_up() -> None:
    """입력 허용 목록에 pg_sleep을 넣지 않고, 예산을 0으로 줄여 재현한다."""
    result = _validate(_inventory_ddl(), budget_seconds=0)
    execute = next(s for s in result.stages if s.stage == "sandbox_execute")
    assert (result.state, execute.problems[0].kind) == ("error", "budget_exceeded")
    assert (_states(result)["rollback"], _states(result)["residual_check"]) == ("passed", "passed")
    assert _check_schemas() == []


# ── 환경 ─────────────────────────────────────────────────────────────


def test_wrong_port_is_a_connection_error_without_cleanup_claims() -> None:
    settings = Settings(
        _env_file=None,
        sandbox_database_url="postgresql://specton_sandbox:x@localhost:1/specton_sandbox",
    )
    result = validate_sql(
        b'CREATE TABLE "t" ("a" integer);',
        settings=settings,
        limits=SandboxLimits(connect_seconds=2),
    )
    assert result.state == "error"
    assert _states(result)["rollback"] == "not_run"
    assert "x@localhost" not in result.model_dump_json()  # 접속 정보는 결과에 없다


def test_app_database_url_is_rejected_by_preflight() -> None:
    """실수로 sandbox 주소를 앱 DB로 잡아도 실행하지 않는다 (sandbox 계정은 앱 DB에 못 붙음)."""
    settings = Settings(
        _env_file=None,
        sandbox_database_url=str(SETTINGS.app_database_url),  # 앱 계정·앱 DB
    )
    result = validate_sql(b'CREATE TABLE "t" ("a" integer);', settings=settings)
    execute = next(s for s in result.stages if s.stage == "sandbox_execute")
    assert (result.state, execute.problems[0].kind) == ("error", "environment")


@pytest.mark.parametrize("suffix", ["/review_path?dbname=specton_sandbox", "/specton%5Fsandbox"])
def test_effective_app_database_is_rejected_before_creating_schema(suffix: str) -> None:
    """실제 접속한 sandbox를 앱 DB로 지정하면 URL 표기와 무관하게 실행을 막는다."""
    settings = Settings(
        _env_file=None,
        sandbox_database_url=URL,
        app_database_url="postgresql://review_user@127.0.0.1" + suffix,
    )
    before = _check_schemas()
    result = validate_sql(b"CREATE TABLE guard_probe (id integer);", settings=settings)
    execute = next(s for s in result.stages if s.stage == "sandbox_execute")
    assert result.state == "error"
    assert execute.problems[0].kind == "environment"
    assert "앱 DB에 접속함" in execute.problems[0].detail
    assert _states(result)["rollback"] == _states(result)["residual_check"] == "passed"
    assert _check_schemas() == before
