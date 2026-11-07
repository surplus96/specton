"""SQL 검증 뒤 세 단계 (#15): 격리 DB 실행 → 롤백 → 잔여 객체 확인. **임시 구현.**

`validate_sql`은 받은 SQL 바이트를 먼저 `check_allowed_sql`로 다시 검사한다. 밖에서 넘긴 통과
결과를 믿고 실행하지 않는다. 앞 두 단계를 통과한 SQL만 격리 DB(`settings.sandbox_database_url`)에서
실행한다.

실행 구조 (설계: `.ai-workspace/15-sandbox-design.md` 3절):
1. 전용 연결을 새로 연다. 앱 DB 연결 풀은 쓰지 않는다. autocommit을 끄고 `with connect` 블록을 쓰지
   않는다(정상 종료 때 자동 commit하지 않게).
2. 사전 확인: 주요 버전 18, 슈퍼유저·DB 생성·역할 생성 권한 없음, 앱 DB에 접속할 수 없음, 앱 DB가
   아님. 하나라도 어긋나면 SQL 결함이 아니라 실행 환경 문제(`error`)다.
3. 검증마다 코드가 만든 이름의 스키마(`specton_check_<uuid>`)를 트랜잭션 안에서 만들고, 검색 경로를
   그 스키마와 `pg_temp`로 고정한다. 문장 하나·잠금 대기 시간 제한을 트랜잭션 안에서 건다.
4. 원본 SQL을 pglast가 알려 준 문장 위치로 잘라 한 문장씩 실행한다(세미콜론으로 자르지 않음).
   그래야 몇 번째 문장에서 실패했는지 남는다. SQL 전체 시간은 클라이언트 타이머가 넘으면 진행 중
   문장을 취소한다.
5. 성공해도 COMMIT하지 않는다. 실패·시간 초과·예외에도 롤백을 시도하고 연결을 닫는다.
6. 새 연결로 검증 스키마가 없는지 확인한다. 남은 것을 DROP으로 지워 통과처럼 만들지 않는다.

오류 분류: SQL 결함으로 확인된 SQLSTATE(`_SQL_DEFECTS`)만 `failed`이고 나머지는 모두 `error`다.
`failed`만 PostgreSQL의 기본 오류 문장을 남기고, `error`는 코드·SQLSTATE만 남긴다(내부 메시지·접속
정보를 결과에 넣지 않음).

규칙 상태:
- 확정 (문서): 제한 계정·허용 문장·시간 제한, 실행기가 트랜잭션 소유, 잔여 객체 확인 (docs/11)
- R4 제안 (#15·#167 확인 전): 시간 제한 값, SQLSTATE 분류표, 검증 스키마 방식, 결과 모양

이 모듈은 LLM client를 import하지 않고 앱 DB에 쓰지 않는다.
"""

import contextlib
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import psycopg
from pglast import parse_sql
from psycopg import sql as pgsql

from specton.config import Settings
from specton.validate.allowed_sql import (
    ProblemKind,
    SqlProblem,
    SqlValidation,
    StageName,
    StageResult,
    build_result,
    check_allowed_sql,
)

TARGET_MAJOR_VERSION = 18  # 대상 PostgreSQL 주요 버전 (DDL 생성기 대상과 같음)
SCHEMA_PREFIX = "specton_check_"

# SQL 결함으로 확인된 SQLSTATE. 여기 없는 오류는 SQL 탓이라고 단정하지 않고 `error`로 둔다.
_SQL_DEFECTS: dict[str, str] = {
    "42P01": "undefined_table",
    "42703": "undefined_column",
    "42830": "invalid_foreign_key",
    "42804": "datatype_mismatch",
    "42P07": "duplicate_table",
    "42701": "duplicate_column",
    "42710": "duplicate_object",
    "42P16": "invalid_table_definition",
    "42611": "invalid_column_definition",
    "42P10": "invalid_column_reference",
    "22023": "invalid_parameter_value",
    "22003": "numeric_value_out_of_range",
    "42601": "syntax_error",
    "0A000": "feature_not_supported",
}
_QUERY_CANCELED = "57014"
_LOCK_NOT_AVAILABLE = "55P03"

Connect = Callable[..., Any]


@dataclass(frozen=True)
class SandboxLimits:
    """시간 제한(초). 기본값은 제안이며 테스트에서 줄여 쓴다."""

    connect_seconds: float = 5
    statement_seconds: float = 10  # 문장 하나 (statement_timeout)
    lock_seconds: float = 2  # 잠금 대기 (lock_timeout)
    budget_seconds: float = 10  # SQL 전체 (클라이언트 타이머)
    residual_seconds: float = 5  # 잔여 확인 연결의 문장 제한


DEFAULT_LIMITS = SandboxLimits()


def validate_sql(
    sql: bytes,
    *,
    settings: Settings,
    limits: SandboxLimits = DEFAULT_LIMITS,
    connect: Connect = psycopg.connect,
) -> SqlValidation:
    """5단계 검증. 앞 두 단계를 통과하지 못하면 DB에 연결하지 않고 그 결과를 돌려준다."""
    first = check_allowed_sql(sql)
    if first.state != "unverified":
        return first
    statements = _statement_texts(sql.decode("utf-8"))
    run = _SandboxRun(
        url=str(settings.sandbox_database_url),
        app_database=_database_name(str(settings.app_database_url)),
        limits=limits,
        connect=connect,
    )
    return build_result(sql, [*first.stages[:2], *run.run(statements)])


def _statement_texts(text: str) -> list[str]:
    """pglast의 문장 위치(글자 단위)로 원본을 자른다. 문장을 다시 만들지 않는다."""
    pieces = []
    for raw in parse_sql(text):
        start = raw.stmt_location or 0
        end = start + raw.stmt_len if raw.stmt_len else len(text)  # 마지막 문장은 길이 0
        pieces.append(text[start:end])
    return pieces


def _database_name(url: str) -> str:
    return urlsplit(url).path.lstrip("/")


@dataclass
class _SandboxRun:
    url: str
    app_database: str
    limits: SandboxLimits
    connect: Connect
    # 취소 요청이 제한 시간 안에 끝나지 않은 예산 타이머. 그동안 연결은 취소 스레드가 쓴다.
    _unsettled: "_BudgetTimer | None" = field(default=None, init=False)

    def run(self, statements: list[str]) -> list[StageResult]:
        schema = f"{SCHEMA_PREFIX}{uuid.uuid4().hex}"
        try:
            conn = self.connect(
                self.url, connect_timeout=self.limits.connect_seconds, autocommit=False
            )
        except Exception as exc:
            # 연결 전이라 트랜잭션이 없다. 롤백·잔여 확인은 실행하지 않은 것으로 둔다.
            return [_error("sandbox_execute", "connection", exc)]
        try:
            execute = self._execute(conn, schema, statements)
        except BaseException:
            _rollback(conn)
            _close(conn)
            raise
        if self._unsettled is not None and self._unsettled.defer(lambda: _cleanup(conn)):
            # 취소 요청이 아직 연결을 쓰고 있다. 같은 연결로 롤백·닫기를 동시에 하지 않고, 취소가
            # 끝나면 취소 스레드가 이어서 정리한다. 여기서는 정리를 확인하지 못했으므로 롤백은
            # `error`, 잔여 확인은 하지 않는다(다른 세션에서는 끝나지 않은 트랜잭션의 스키마가
            # 보이지 않아, 지금 확인하면 「남지 않음」으로 잘못 나온다).
            pending = _problem("rollback_failed", "실행 취소가 끝나지 않아 롤백을 확인하지 못함")
            return [execute, _stage("rollback", "error", pending)]
        rollback = _rollback(conn)
        _close(conn)
        return [execute, rollback, self._residual(schema)]

    def _execute(self, conn: Any, schema: str, statements: list[str]) -> StageResult:
        try:
            problem = self._preflight(conn)
            if problem is not None:
                return _stage("sandbox_execute", "error", problem)
            conn.execute(pgsql.SQL("CREATE SCHEMA {}").format(pgsql.Identifier(schema)))
            conn.execute(
                pgsql.SQL("SET LOCAL search_path = {}, pg_temp").format(pgsql.Identifier(schema))
            )
            conn.execute(
                "SELECT set_config('statement_timeout', %s, true),"
                " set_config('lock_timeout', %s, true)",
                (_ms(self.limits.statement_seconds), _ms(self.limits.lock_seconds)),
            )
        except Exception as exc:
            # 준비 단계 실패는 SQL 결함이 아니다.
            return _error("sandbox_execute", _env_code(exc), exc)
        return self._run_statements(conn, statements)

    def _preflight(self, conn: Any) -> SqlProblem | None:
        row = conn.execute(
            "SELECT current_setting('server_version_num')::int / 10000,"
            " current_database(), r.rolsuper, r.rolcreatedb, r.rolcreaterole,"
            " EXISTS (SELECT 1 FROM pg_database d WHERE d.datname = %s"
            "         AND has_database_privilege(d.datname, 'CONNECT'))"
            " FROM pg_roles r WHERE r.rolname = current_user",
            (self.app_database,),
        ).fetchone()
        if row is None:
            return _problem("environment", "현재 계정 정보를 찾지 못함")
        major, database, superuser, createdb, createrole, app_connect = row
        reasons = [
            *([f"PostgreSQL 주요 버전이 {major}"] if major != TARGET_MAJOR_VERSION else []),
            *(["앱 DB에 접속함"] if database == self.app_database else []),
            *(["슈퍼유저 계정"] if superuser else []),
            *(["DB 생성 권한이 있음"] if createdb else []),
            *(["역할 생성 권한이 있음"] if createrole else []),
            *(["앱 DB 접속 권한이 있음"] if app_connect else []),
        ]
        if reasons:
            return _problem("environment", "격리 DB 사전 확인 실패: " + ", ".join(reasons))
        return None

    def _run_statements(self, conn: Any, statements: list[str]) -> StageResult:
        budget = _BudgetTimer(conn, self.limits)
        budget.start()
        result: StageResult | None = None
        try:
            for index, text in enumerate(statements):
                if budget.over():
                    result = _stage("sandbox_execute", "error", _budget_problem(index))
                    break
                try:
                    conn.execute(text)
                except psycopg.Error as exc:
                    result = _classify(exc, index, budget_fired=budget.fired.is_set())
                    break
                except Exception as exc:
                    result = _error("sandbox_execute", "internal", exc, statement=index)
                    break
        finally:
            # 취소가 진행 중이면 끝날 때까지 기다린다. 그 뒤에야 롤백·닫기를 한다.
            settled = budget.stop()
        if not settled:
            self._unsettled = budget
            problem = _problem("database", "실행 취소 작업이 제한 시간 안에 끝나지 않음")
            return _stage("sandbox_execute", "error", problem)
        if result is not None:
            return result
        # 마지막 문장 뒤: 타이머 콜백이 늦게 돌았어도 마감 시간을 넘겼으면 통과가 아니다.
        if budget.over():
            return _stage("sandbox_execute", "error", _budget_problem(None))
        return StageResult(stage="sandbox_execute", state="passed")

    def _residual(self, schema: str) -> StageResult:
        """새 연결로 검증 스키마가 없는지 본다. 남은 것은 지우지 않고 그대로 보고한다."""
        try:
            check = self.connect(
                self.url, connect_timeout=self.limits.connect_seconds, autocommit=True
            )
        except Exception as exc:
            return _error("residual_check", "residual_check_failed", exc)
        try:
            check.execute(
                "SELECT set_config('statement_timeout', %s, false)",
                (_ms(self.limits.residual_seconds),),
            )
            found = check.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)", (schema,)
            ).fetchone()
        except Exception as exc:
            return _error("residual_check", "residual_check_failed", exc)
        finally:
            _close(check)
        if found is None or found[0]:
            return _stage(
                "residual_check", "error", _problem("residual_found", "검증 스키마가 남아 있음")
            )
        return StageResult(stage="residual_check", state="passed")


# ── 전체 시간 예산 ───────────────────────────────────────────────────


class _BudgetTimer:
    """SQL 전체 실행 예산. 시간이 지나면 진행 중 문장을 취소한다.

    취소 콜백과 정리(롤백·닫기)가 겹치지 않게 한다.
    - 콜백은 잠금 안에서 `stopped`를 확인한 뒤에만 취소한다. `stop()`이 먼저 잠금을 잡고
      `stopped`를 세우면 그 뒤 콜백은 아무것도 하지 않는다.
    - `stop()`은 이미 시작한 콜백(취소 요청)이 끝날 때까지 스레드를 기다린다. `cancel_safe`는 자체
      제한 시간이 있어 기다림도 유한하다. 그래도 끝나지 않으면 False를 돌려준다.
    - 통과 여부는 콜백 실행 여부(`fired`)와 함께 마감 시각(`monotonic`)으로도 판단한다. 콜백이
      늦게 돌아도 예산 초과를 통과로 내지 않는다.
    - 기다려도 취소가 끝나지 않으면 연결을 취소 스레드에 넘긴다(`defer`). 롤백·닫기는 취소가 끝난
      뒤 그 스레드가 실행해, 같은 연결을 두 스레드가 동시에 쓰지 않는다.
    """

    def __init__(self, conn: Any, limits: SandboxLimits) -> None:
        self._conn = conn
        self._cancel_seconds = limits.connect_seconds
        self.deadline = time.monotonic() + limits.budget_seconds
        self.fired = threading.Event()
        self._lock = threading.Lock()
        self._stopped = False
        self._handoff = threading.Lock()
        self._cancel_finished = False
        self._after: Callable[[], None] | None = None
        self._timer = threading.Timer(limits.budget_seconds, self._cancel)
        self._timer.daemon = True

    def start(self) -> None:
        self._timer.start()

    def over(self) -> bool:
        return self.fired.is_set() or time.monotonic() > self.deadline

    def _cancel(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self.fired.set()
            # 취소 실패는 실행 결과·마감 시각 확인으로 드러난다
            with contextlib.suppress(Exception):
                self._conn.cancel_safe(timeout=self._cancel_seconds)
        with self._handoff:
            self._cancel_finished = True
            after, self._after = self._after, None
        if after is not None:  # 실행 스레드가 넘긴 정리 (취소가 끝난 뒤에만)
            after()

    def defer(self, cleanup: Callable[[], None]) -> bool:
        """취소가 아직 진행 중이면 정리를 맡기고 True. 이미 끝났으면 False(호출한 쪽이 정리)."""
        with self._handoff:
            if self._cancel_finished:
                return False
            self._after = cleanup
            return True

    def stop(self) -> bool:
        """더 이상 취소하지 않게 하고, 진행 중인 취소가 끝날 때까지 기다린다."""
        self._timer.cancel()
        acquired = self._lock.acquire(timeout=self._cancel_seconds + 1)
        if not acquired:  # 취소 요청이 제한 시간을 넘겨 붙잡혀 있다
            return False
        try:
            self._stopped = True
        finally:
            self._lock.release()
        if self._timer.is_alive():
            self._timer.join(timeout=self._cancel_seconds + 1)
        return not self._timer.is_alive()


# ── 정리 ─────────────────────────────────────────────────────────────


def _rollback(conn: Any) -> StageResult:
    try:
        conn.rollback()
    except Exception as exc:
        return _error("rollback", "rollback_failed", exc)
    return StageResult(stage="rollback", state="passed")


def _cleanup(conn: Any) -> None:
    """넘겨받은 연결 정리. 결과에는 반영하지 못하므로 실패해도 조용히 끝낸다."""
    _rollback(conn)
    _close(conn)


def _close(conn: Any) -> None:
    with contextlib.suppress(Exception):  # 닫기 실패는 결과를 바꾸지 않는다
        conn.close()


# ── 분류 ─────────────────────────────────────────────────────────────


def _classify(exc: psycopg.Error, statement: int, *, budget_fired: bool) -> StageResult:
    state = exc.sqlstate
    if state in _SQL_DEFECTS:
        message = (exc.diag.message_primary or _SQL_DEFECTS[state]).strip()
        problem = SqlProblem(
            kind="execution_error",
            statement=statement,
            detail=f"{_SQL_DEFECTS[state]}: {message}",
            sqlstate=state,
        )
        return _stage("sandbox_execute", "failed", problem)
    if state == _QUERY_CANCELED:
        kind: ProblemKind = "budget_exceeded" if budget_fired else "timeout"
    elif state == _LOCK_NOT_AVAILABLE:
        kind = "lock_timeout"
    else:
        kind = _env_code(exc)
    return _error("sandbox_execute", kind, exc, statement=statement)


def _env_code(exc: BaseException) -> ProblemKind:
    state = getattr(exc, "sqlstate", None) or ""
    if state.startswith("08") or (isinstance(exc, psycopg.OperationalError) and not state):
        return "connection"
    if state == "42501" or state.startswith("28") or state == "3D000":
        return "environment"
    if isinstance(exc, psycopg.Error):
        return "database"
    return "internal"


def _budget_problem(statement: int | None) -> SqlProblem:
    return _problem("budget_exceeded", "SQL 전체 실행 시간 예산을 넘음", statement=statement)


def _error(
    stage: StageName, kind: ProblemKind, exc: BaseException, *, statement: int | None = None
) -> StageResult:
    """장애 결과. 내부 메시지는 넣지 않고 종류·SQLSTATE·예외 이름만 남긴다."""
    state = getattr(exc, "sqlstate", None)
    problem = SqlProblem(kind=kind, statement=statement, detail=type(exc).__name__, sqlstate=state)
    return _stage(stage, "error", problem)


def _problem(kind: ProblemKind, detail: str, *, statement: int | None = None) -> SqlProblem:
    return SqlProblem(kind=kind, statement=statement, detail=detail)


def _stage(stage: StageName, state: Any, problem: SqlProblem) -> StageResult:
    return StageResult(stage=stage, state=state, problems=(problem,))


def _ms(seconds: float) -> str:
    return f"{int(seconds * 1000)}ms"
