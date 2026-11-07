"""SQL 검증 앞 두 단계 (#15): 파싱 → 허용 SQL 검사. DB에 접속하지 않는다. **임시 구현.**

검증기 전체는 5단계(파싱 → 허용 SQL 검사 → 격리 DB 실행 → 롤백 → 잔여 객체 확인)다(#167 제안).
이 모듈은 앞 두 단계만 실행하고, 뒤 세 단계는 `not_run`으로 남긴다. 그래서 정상 SQL도 전체 상태는
`unverified`이며 `passed`가 되지 않는다. 뒤 세 단계는 `specton.validate.sandbox`가 같은 결과 모양에
채운다.

허용 목록 방식이다. DDL 생성기(#165)가 내는 두 문장만 받는다.
- `CREATE TABLE`: 칸(허용 타입 11개), `NOT NULL`·`NULL`, `PRIMARY KEY`·`UNIQUE`·`REFERENCES`
- `ALTER TABLE ... ADD FOREIGN KEY`: 명령 하나에 FK 하나

pglast 노드마다 「쓰는 칸」만 정해 두고, 나머지 칸은 비어 있어야(기본값) 한다. 그래서 옵션
(`WITH (...)`, `TABLESPACE`, `DEFERRABLE` 등)이나 pglast가 새로 더한 칸은 따로 적지 않아도 막힌다.

규칙 상태:
- 확정 (문서): 실행 전 문법 검사·허용 AST 정의(docs/11), 트랜잭션 제어는 실행기 소유(docs/11),
  허용 타입 11개(docs/05)
- R4 제안 (#15·#167 확인 전): 결과 모양(단계별 결과, unverified/passed/failed/error),
  허용 문장 목록, 제약 이름 허용, FK 동작은 기본값만,
  스키마 없는 내장 타입(`text`·`date`·`timestamptz`) 허용
- 한계: 스키마 없는 타입 이름은 실제 DB의 `search_path`로 해석된다. 이 모듈은 이름 모양만 보며,
  실제로 내장 타입으로 해석되는지는 격리 DB 단계에서 확인한다.

이 모듈은 LLM client를 import하지 않는다.
"""

import hashlib
from collections.abc import Iterable, Iterator
from typing import Any, Literal

from pglast import ast, parse_sql
from pglast.enums import AlterTableType, ConstrType, ObjectType
from pglast.parser import ParseError
from pydantic import BaseModel, ConfigDict

from specton.contracts.base import SqlType

VALIDATOR_VERSION = "sql-validator-v1"  # 검증기 동작이 바뀌면 올린다. 임시 값이다. v1: 격리 DB 단계
POLICY_VERSION = "allowed-sql-v0"  # 허용 목록이 바뀌면 올린다. 임시 값이다.
# 대상 DB. DDL 생성기(#165 `DDL_TARGET`)와 같은 값이다. #165 병합 뒤 한 곳으로 합친다.
TARGET = "postgresql-18"

StageName = Literal["parse", "allowed_sql", "sandbox_execute", "rollback", "residual_check"]
StageState = Literal["passed", "failed", "error", "not_run"]
OverallState = Literal["unverified", "passed", "failed", "error"]
ProblemKind = Literal[
    "parse_error",
    "not_allowed",
    "empty",
    "not_utf8",
    "nul_byte",
    "internal",
    # 격리 DB 단계 (specton.validate.sandbox)
    "execution_error",  # SQL 결함으로 확인된 실행 오류 (failed)
    "connection",  # 연결 실패·끊김
    "environment",  # 권한·사전 확인 실패 등 실행 환경 문제
    "timeout",  # 문장 하나의 시간 제한
    "budget_exceeded",  # SQL 전체 실행 예산
    "lock_timeout",  # 잠금 대기 시간 제한
    "database",  # 그 밖의 DB 장애
    "rollback_failed",
    "residual_found",  # 검증 스키마가 남음
    "residual_check_failed",  # 남았는지 확인하지 못함
]
STAGES: tuple[StageName, ...] = (
    "parse",
    "allowed_sql",
    "sandbox_execute",
    "rollback",
    "residual_check",
)

# 허용 타입 → pglast가 내놓는 정확한 이름(pglast 8.7로 확인). 파서는 대부분의 내장 타입에
# `pg_catalog`를 붙이고, `text`·`date`·`timestamptz`는 한 부분 이름으로 남긴다. 마지막 이름만 보지
# 않는다: `public.int4`, `"int4"`, `pg_catalog.text`처럼 모양이 다르면 거절한다.
_TYPE_NAMES: dict[SqlType, tuple[str, ...]] = {
    SqlType.CHAR: ("pg_catalog", "bpchar"),
    SqlType.VARCHAR: ("pg_catalog", "varchar"),
    SqlType.TEXT: ("text",),
    SqlType.NUMERIC: ("pg_catalog", "numeric"),
    SqlType.INTEGER: ("pg_catalog", "int4"),
    SqlType.BIGINT: ("pg_catalog", "int8"),
    SqlType.BOOLEAN: ("pg_catalog", "bool"),
    SqlType.DATE: ("date",),
    SqlType.TIME: ("pg_catalog", "time"),
    SqlType.TIMESTAMP: ("pg_catalog", "timestamp"),
    SqlType.TIMESTAMPTZ: ("timestamptz",),
}
_TYPE_BY_NAMES = {names: kind for kind, names in _TYPE_NAMES.items()}
# 타입별 괄호 안 숫자 개수 (최소, 최대)
_TYPMODS: dict[SqlType, tuple[int, int]] = {
    SqlType.CHAR: (1, 1),
    SqlType.VARCHAR: (1, 1),
    SqlType.NUMERIC: (0, 2),
    SqlType.TIME: (0, 1),
    SqlType.TIMESTAMP: (0, 1),
    SqlType.TIMESTAMPTZ: (0, 1),
}
# FK 기본값: MATCH SIMPLE, ON UPDATE/DELETE NO ACTION
_FK_MATCH_SIMPLE = "s"
_FK_NO_ACTION = "a"
_PERMANENT = "p"  # RangeVar.relpersistence: 일반 테이블 (TEMP 't', UNLOGGED 'u')
_IGNORED = frozenset({"location", "stmt_location", "stmt_len"})


class SqlProblem(BaseModel):
    """검증 문제 한 건. `detail`은 사람이 읽는 이유이며 내부 경로·비밀값을 담지 않는다."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ProblemKind
    statement: int | None  # 몇 번째 문장(0부터). 문장 단위가 아니면 None
    detail: str
    sqlstate: str | None = None  # DB 오류 코드 (격리 DB 단계)


class StageResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: StageName
    state: StageState
    problems: tuple[SqlProblem, ...] = ()


class SqlValidation(BaseModel):
    """SQL 검증 결과. 공용 계약이 아닌 임시 모양이다(#167에서 저장·승인 연결과 함께 정한다).

    실행 revision·model_hash·snapshot_id는 검증기가 모르므로 넣지 않는다. 연결하는 쪽이 넘긴다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: OverallState
    stages: tuple[StageResult, ...]  # 5단계, 순서 고정
    sql_sha256: str  # 받은 바이트 전체의 SHA-256 (#163 ArtifactRef.hash와 같은 계산)
    validator_version: str
    policy_version: str
    target: str


def check_allowed_sql(sql: bytes) -> SqlValidation:
    """파싱·허용 SQL 검사를 한다. 뒤 세 단계는 `not_run`이다."""
    parse = _parse_stage(sql)
    if isinstance(parse, StageResult):
        done = [parse]
    else:
        statements = parse
        done = [StageResult(stage="parse", state="passed"), _allowed_stage(statements)]
    return build_result(sql, done)


def build_result(sql: bytes, done: Iterable[StageResult]) -> SqlValidation:
    """실행한 단계 결과로 전체 결과를 만든다. 실행하지 않은 단계는 `not_run`으로 채운다.

    앞 단계가 실패·장애이면 뒤 단계는 실행하지 않는다. 예외는 정리 단계(롤백·잔여 확인)다:
    격리 DB에서 실행이 실패해도 롤백과 잔여 확인은 시도하고 그 결과를 남긴다 (`sandbox`).
    """
    done = tuple(done)
    names = [s.stage for s in done]
    unknown = set(names) - set(STAGES)
    if unknown:
        raise ValueError(f"모르는 단계: {sorted(unknown)}")
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        # 뒤 결과로 앞 결과(예: 실패)를 덮어쓰지 않도록 거절한다.
        raise ValueError(f"같은 단계 결과가 두 번 있음: {duplicated}")
    by_stage = {s.stage: s for s in done}
    stages = tuple(by_stage.get(name, StageResult(stage=name, state="not_run")) for name in STAGES)
    return SqlValidation(
        state=overall_state(stages),
        stages=stages,
        sql_sha256=hashlib.sha256(sql).hexdigest(),
        validator_version=VALIDATOR_VERSION,
        policy_version=POLICY_VERSION,
        target=TARGET,
    )


def overall_state(stages: Iterable[StageResult]) -> OverallState:
    """전체 상태. `error`가 가장 우선이고, 그다음 `failed`, 남은 단계가 있으면 `unverified`다.

    SQL 결함 뒤 정리(롤백)까지 실패하면 둘 다 알아야 하므로 `error`로 올리고, 결함은 단계 결과에
    `failed`로 그대로 남긴다 (#167 검토). 5단계가 순서대로 한 번씩 있어야 계산한다. 빈 목록이나
    일부 단계만으로 `passed`가 나오지 않게 한다.
    """
    stages = tuple(stages)
    if tuple(s.stage for s in stages) != STAGES:
        raise ValueError(f"5단계가 순서대로 한 번씩 있어야 함: {[s.stage for s in stages]}")
    states = [s.state for s in stages]
    if "error" in states:
        return "error"
    if "failed" in states:
        return "failed"
    if "not_run" in states:
        return "unverified"
    return "passed"


# ── 1단계: 파싱 ─────────────────────────────────────────────────────


def _parse_stage(sql: bytes) -> StageResult | tuple[Any, ...]:
    def failed(kind: ProblemKind, detail: str) -> StageResult:
        problem = SqlProblem(kind=kind, statement=None, detail=detail)
        return StageResult(stage="parse", state="failed", problems=(problem,))

    # pglast는 NUL에서 문자열이 끝난 것으로 보고 뒤를 읽지 않는다. 앞부분만 검사하고 전체 해시를
    # 남기지 않도록 파싱 전에 막는다.
    if b"\x00" in sql:
        return failed("nul_byte", f"NUL 바이트가 있음 (위치 {sql.index(b'\x00')})")
    try:
        text = sql.decode("utf-8")
    except UnicodeDecodeError as exc:
        return failed("not_utf8", f"UTF-8이 아닌 바이트 (위치 {exc.start})")
    try:
        statements = parse_sql(text)
    except ParseError as exc:
        return failed("parse_error", f"문법 오류: {exc}")
    except Exception as exc:  # 파서 장애는 SQL 결함이 아니라 검증 장애다
        problem = SqlProblem(kind="internal", statement=None, detail=type(exc).__name__)
        return StageResult(stage="parse", state="error", problems=(problem,))
    if not statements:
        return failed("empty", "실행할 문장이 없음")
    return tuple(raw.stmt for raw in statements)


# ── 2단계: 허용 SQL 검사 ───────────────────────────────────────────


def _allowed_stage(statements: tuple[Any, ...]) -> StageResult:
    try:
        problems = [
            SqlProblem(kind="not_allowed", statement=i, detail=detail)
            for i, stmt in enumerate(statements)
            for detail in _statement_problems(stmt)
        ]
    except Exception as exc:  # 검사기 장애는 SQL 결함과 구분한다
        problem = SqlProblem(kind="internal", statement=None, detail=type(exc).__name__)
        return StageResult(stage="allowed_sql", state="error", problems=(problem,))
    state: StageState = "failed" if problems else "passed"
    return StageResult(stage="allowed_sql", state=state, problems=tuple(problems))


def _statement_problems(stmt: Any) -> Iterator[str]:
    if isinstance(stmt, ast.CreateStmt):
        yield from _create_table(stmt)
    elif isinstance(stmt, ast.AlterTableStmt):
        yield from _alter_table(stmt)
    else:
        yield f"허용하지 않는 문장: {type(stmt).__name__}"


def _create_table(stmt: ast.CreateStmt) -> Iterator[str]:
    yield from _extra(stmt, {"relation", "tableElts"}, "CREATE TABLE")
    yield from _relation(stmt.relation, "CREATE TABLE")
    if not stmt.tableElts:
        yield "CREATE TABLE: 칸이 없음"
    for elt in stmt.tableElts or ():
        if isinstance(elt, ast.ColumnDef):
            yield from _column(elt)
        elif isinstance(elt, ast.Constraint):
            yield from _constraint(elt, f"표 제약 {_contype_name(elt)}", table_level=True)
        else:
            yield f"CREATE TABLE: 허용하지 않는 요소 {type(elt).__name__}"


def _alter_table(stmt: ast.AlterTableStmt) -> Iterator[str]:
    where = "ALTER TABLE"
    yield from _extra(stmt, {"relation", "cmds", "objtype"}, where)
    if stmt.objtype != ObjectType.OBJECT_TABLE:
        yield f"{where}: 테이블 대상이 아님"
    yield from _relation(stmt.relation, where)
    cmds = stmt.cmds or ()
    if len(cmds) != 1:
        yield f"{where}: 하위 명령은 하나만 허용 ({len(cmds)}개)"
    for cmd in cmds:
        if not isinstance(cmd, ast.AlterTableCmd) or cmd.subtype != AlterTableType.AT_AddConstraint:
            yield f"{where}: 허용하지 않는 하위 명령 {_name(getattr(cmd, 'subtype', cmd))}"
            continue
        yield from _extra(cmd, {"subtype", "def_", "behavior"}, f"{where} 하위 명령")
        con = cmd.def_
        if not isinstance(con, ast.Constraint) or con.contype != ConstrType.CONSTR_FOREIGN:
            yield f"{where}: FOREIGN KEY 추가만 허용"
            continue
        yield from _constraint(con, f"{where} FOREIGN KEY", table_level=True)


def _relation(rel: Any, where: str) -> Iterator[str]:
    """테이블 이름. 스키마·카탈로그 지정, TEMP·UNLOGGED, ONLY는 거절한다."""
    if not isinstance(rel, ast.RangeVar):
        yield f"{where}: 테이블 이름이 없음"
        return
    yield from _extra(rel, {"relname", "inh", "relpersistence"}, f"{where} 테이블 {rel.relname}")
    if rel.schemaname or rel.catalogname:
        yield f"{where}: 스키마를 붙인 테이블 이름은 허용하지 않음 ({rel.schemaname}.{rel.relname})"
    if rel.relpersistence != _PERMANENT:
        yield f"{where}: 일반 테이블만 허용 (TEMP·UNLOGGED 거절)"
    if not rel.inh:
        yield f"{where}: ONLY는 허용하지 않음"


def _column(col: ast.ColumnDef) -> Iterator[str]:
    where = f"칸 {col.colname}"
    allowed = {"colname", "typeName", "constraints", "is_local", "inhcount"}
    yield from _extra(col, allowed, where)
    if not col.is_local or col.inhcount:
        yield f"{where}: 상속 칸은 허용하지 않음"
    yield from _type(col.typeName, where)
    for con in col.constraints or ():
        yield from _constraint(con, f"{where} 제약 {_contype_name(con)}", table_level=False)


def _type(tn: Any, where: str) -> Iterator[str]:
    if not isinstance(tn, ast.TypeName):
        yield f"{where}: 타입이 없음"
        return
    yield from _extra(tn, {"names", "typmods", "typemod"}, f"{where} 타입")
    if tn.typemod != -1:
        yield f"{where}: 타입 수식 값은 허용하지 않음"
    names = tuple(getattr(n, "sval", None) for n in tn.names or ())
    kind = _TYPE_BY_NAMES.get(names)  # type: ignore[arg-type]
    if kind is None:
        yield f"{where}: 허용하지 않는 타입 {'.'.join(str(n) for n in names)}"
        return
    mods = tn.typmods or ()
    low, high = _TYPMODS.get(kind, (0, 0))
    if not low <= len(mods) <= high:
        yield f"{where}: {kind.value} 괄호 안 숫자는 {low}~{high}개 ({len(mods)}개)"
    for mod in mods:
        if not (
            isinstance(mod, ast.A_Const)
            and not mod.isnull
            and isinstance(mod.val, ast.Integer)
            and isinstance(mod.val.ival, int)
            and mod.val.ival >= 0
        ):
            yield f"{where}: 타입 괄호 안에는 0 이상의 정수만 허용"


def _constraint(con: Any, where: str, *, table_level: bool) -> Iterator[str]:
    """제약. 표에 붙인 것과 칸에 붙인 것을 같은 규칙으로 본다. 옵션(`WITH`)·`TABLESPACE`·
    `DEFERRABLE`·`NOT VALID`·`NO INHERIT` 등은 비어 있어야 한다(`_extra`).
    """
    if not isinstance(con, ast.Constraint):
        yield f"{where}: 제약이 아님"
        return
    kind = con.contype
    # 기본값이 제약 종류마다 달라(예: FK는 is_enforced=True) 종류별로 따로 본다.
    flags = {"contype", "conname", "is_enforced", "initially_valid"}
    if kind in (ConstrType.CONSTR_NULL, ConstrType.CONSTR_NOTNULL):
        if table_level:
            yield f"{where}: 표 제약으로는 허용하지 않음"
        yield from _extra(con, flags, where)
        if kind == ConstrType.CONSTR_NOTNULL and not (con.is_enforced and con.initially_valid):
            yield f"{where}: NOT NULL 옵션은 허용하지 않음"
    elif kind in (ConstrType.CONSTR_PRIMARY, ConstrType.CONSTR_UNIQUE):
        yield from _extra(con, flags | ({"keys"} if table_level else set()), where)
        if table_level:
            yield from _names(con.keys, where)
    elif kind == ConstrType.CONSTR_FOREIGN:
        allowed = flags | {"pktable", "pk_attrs", "fk_matchtype", "fk_upd_action", "fk_del_action"}
        yield from _extra(con, allowed | ({"fk_attrs"} if table_level else set()), where)
        if not (con.is_enforced and con.initially_valid):
            yield f"{where}: NOT ENFORCED·NOT VALID는 허용하지 않음"
        yield from _relation(con.pktable, f"{where} 참조")
        if table_level:
            yield from _names(con.fk_attrs, where)
        if con.pk_attrs is not None:
            yield from _names(con.pk_attrs, where)
        if con.fk_matchtype != _FK_MATCH_SIMPLE:
            yield f"{where}: MATCH는 기본(SIMPLE)만 허용"
        if con.fk_upd_action != _FK_NO_ACTION or con.fk_del_action != _FK_NO_ACTION:
            yield f"{where}: ON UPDATE·ON DELETE 동작은 기본(NO ACTION)만 허용"
    else:
        yield f"{where}: 허용하지 않는 제약"


def _names(items: Any, where: str) -> Iterator[str]:
    if not items or not all(isinstance(i, ast.String) for i in items):
        yield f"{where}: 칸 이름 목록이 필요함"


# ── 공통 ─────────────────────────────────────────────────────────────


def _extra(node: Any, allowed: set[str], where: str) -> Iterator[str]:
    """허용한 칸 밖에 값이 있으면 문제. pglast가 새 칸을 더해도 값이 차면 막힌다."""
    for field in node:
        if field in allowed or field in _IGNORED:
            continue
        if _is_set(getattr(node, field)):
            yield f"{where}: 허용하지 않는 구성 {field}"


def _is_set(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value not in ("", "\x00")
    if isinstance(value, int):  # 열거형 포함. 기본값은 0
        return value != 0
    if isinstance(value, (tuple, list)):
        return len(value) > 0
    return True


def _contype_name(con: Any) -> str:
    return _name(getattr(con, "contype", con))


def _name(value: Any) -> str:
    return getattr(value, "name", type(value).__name__)
