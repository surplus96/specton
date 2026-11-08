"""SQL 검증 앞 두 단계 (#15): 파싱 → 허용 SQL 검사. DB에 접속하지 않는다. **임시 구현.**

검증기 전체는 5단계(파싱 → 허용 문장 검사 → 격리 DB 실행 → 롤백 → 잔여 객체 확인)다(#167).
결과는 공용 계약 `specton.contracts.SqlValidation`(#176)이다. 이 모듈은 앞 두 단계만 실행하고, 뒤 세
단계는 `not_run`으로 남긴다. 그래서 정상 SQL도 전체 상태는 `unverified`이며 `passed`가 되지 않는다.
뒤 세 단계는 `specton.validate.sandbox`가 같은 결과에 채운다.

허용 목록 방식이다. DDL 생성기(#165)가 내는 두 문장만 받는다.
- `CREATE TABLE`: 칸(허용 타입 11개), `NOT NULL`·`NULL`, `PRIMARY KEY`·`UNIQUE`·`REFERENCES`
- `ALTER TABLE ... ADD FOREIGN KEY`: 명령 하나에 FK 하나

pglast 노드마다 「쓰는 칸」만 정해 두고, 나머지 칸은 비어 있어야(기본값) 한다. 그래서 옵션
(`WITH (...)`, `TABLESPACE`, `DEFERRABLE` 등)이나 pglast가 새로 더한 칸은 따로 적지 않아도 막힌다.

규칙 상태:
- 확정 (문서): 실행 전 문법 검사·허용 AST 정의(docs/11), 트랜잭션 제어는 실행기 소유(docs/11),
  허용 타입 11개(docs/05)
- 확정 (#167·#176): 결과 모양(공용 계약), 대상 DB 값은 DDL 생성기의 `DDL_TARGET`
- R4 제안 (#15 확인 전): 허용 문장 목록, 제약 이름 허용, FK 동작은 기본값만,
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

from specton.codegen.ddl import DDL_TARGET
from specton.contracts import (
    VALIDATION_STEPS,
    SqlValidation,
    StepStatus,
    ValidationIssue,
    ValidationStep,
    ValidationStepName,
    overall_status,
)
from specton.contracts.base import SqlType

# 세 버전은 승인 조건이다 (#167). 값이 바뀌면 이전 검증 기록으로는 승인할 수 없다.
# 검사 결과가 실제로 달라지는 수정일 때만 올린다.
VALIDATOR_VERSION = "sql-validator-v1"  # 검증기 동작이 바뀌면 올린다. 임시 값이다. v1: 격리 DB 단계
POLICY_VERSION = "allowed-sql-v0"  # 허용 목록이 바뀌면 올린다. 임시 값이다.
TARGET = DDL_TARGET  # 대상 DB (`postgres_version`). DDL 생성기와 한 곳에서 정한다

# `ValidationIssue.code` 값
IssueCode = Literal[
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


def issue(
    code: IssueCode, message: str, *, statement: int | None = None, sqlstate: str | None = None
) -> ValidationIssue:
    """문제 한 건. `message`에는 보여도 되는 문장만 넣는다(내부 경로·접속 정보·예외 원문 금지).

    `statement`는 몇 번째 문장인지(0부터)이고, 문장 단위가 아니면 None이다.
    """
    return ValidationIssue(code=code, message=message, statement_index=statement, sqlstate=sqlstate)


def step(name: ValidationStepName, status: StepStatus, *issues: ValidationIssue) -> ValidationStep:
    return ValidationStep(name=name, status=status, issues=issues)


def check_allowed_sql(sql: bytes) -> SqlValidation:
    """파싱·허용 문장 검사를 한다. 뒤 세 단계는 `not_run`이다."""
    parse = _parse_stage(sql)
    if isinstance(parse, ValidationStep):
        done = [parse]
    else:
        statements = parse
        done = [step(ValidationStepName.PARSE, StepStatus.PASSED), _allowed_stage(statements)]
    return build_result(sql, done)


def build_result(sql: bytes, done: Iterable[ValidationStep]) -> SqlValidation:
    """실행한 단계 결과로 공용 결과를 만든다. 실행하지 않은 단계는 `not_run`으로 채운다.

    앞 단계가 실패·장애이면 뒤 단계는 실행하지 않는다. 예외는 정리 단계(롤백·잔여 확인)다:
    격리 DB에서 실행이 실패해도 롤백과 잔여 확인은 시도하고 그 결과를 남긴다 (`sandbox`).
    전체 상태는 계약의 `overall_status`로 정하고, 단계 순서·문제 유무는 계약이 다시 검사한다.
    해시는 받은 바이트 전체의 SHA-256이다 (#163 `ArtifactRef.hash`와 같은 계산).
    """
    done = tuple(done)
    names = [s.name for s in done]
    duplicated = sorted({str(n) for n in names if names.count(n) > 1})
    if duplicated:
        # 뒤 결과로 앞 결과(예: 실패)를 덮어쓰지 않도록 거절한다.
        raise ValueError(f"같은 단계 결과가 두 번 있음: {duplicated}")
    by_name = {s.name: s for s in done}
    steps = tuple(by_name.get(name, step(name, StepStatus.NOT_RUN)) for name in VALIDATION_STEPS)
    return SqlValidation(
        status=overall_status(steps),
        artifact_hash=hashlib.sha256(sql).hexdigest(),
        validator_version=VALIDATOR_VERSION,
        policy_version=POLICY_VERSION,
        postgres_version=TARGET,
        steps=steps,
    )


# ── 1단계: 파싱 ─────────────────────────────────────────────────────


def _parse_stage(sql: bytes) -> ValidationStep | tuple[Any, ...]:
    def failed(code: IssueCode, message: str) -> ValidationStep:
        return step(ValidationStepName.PARSE, StepStatus.FAILED, issue(code, message))

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
        return step(
            ValidationStepName.PARSE, StepStatus.ERROR, issue("internal", type(exc).__name__)
        )
    if not statements:
        return failed("empty", "실행할 문장이 없음")
    return tuple(raw.stmt for raw in statements)


# ── 2단계: 허용 문장 검사 ──────────────────────────────────────────


def _allowed_stage(statements: tuple[Any, ...]) -> ValidationStep:
    name = ValidationStepName.ALLOWED_STATEMENTS
    try:
        issues = [
            issue("not_allowed", detail, statement=i)
            for i, stmt in enumerate(statements)
            for detail in _statement_problems(stmt)
        ]
    except Exception as exc:  # 검사기 장애는 SQL 결함과 구분한다
        return step(name, StepStatus.ERROR, issue("internal", type(exc).__name__))
    status = StepStatus.FAILED if issues else StepStatus.PASSED
    return step(name, status, *issues)


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
