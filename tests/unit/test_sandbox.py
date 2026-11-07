"""격리 DB 실행·롤백·잔여 확인 (#15). 가짜 연결로 순서·분류·정리 보장을 본다. DB에 접속하지 않는다.

실제 PostgreSQL 동작은 `tests/integration/test_sandbox_db.py`(`@pytest.mark.db`)가 확인한다.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import psycopg
import pytest

from specton.config import Settings
from specton.validate import sandbox
from specton.validate.allowed_sql import SqlValidation, StageResult
from specton.validate.sandbox import SCHEMA_PREFIX, SandboxLimits, validate_sql

SQL = (
    b'-- header\nCREATE TABLE "p" ("a" integer NOT NULL, PRIMARY KEY ("a"));\n'
    b'CREATE TABLE "c" ("a" integer);\n'
    b'ALTER TABLE "c" ADD FOREIGN KEY ("a") REFERENCES "p" ("a");\n'
)
SETTINGS = Settings(_env_file=None)
GOOD_ROW = (18, "specton_sandbox", False, False, False, False)


def _db_error(sqlstate: str, message: str = "boom") -> psycopg.Error:
    """sqlstate·진단을 가진 psycopg 오류. 실제 클래스는 SQLSTATE로 고른다."""
    base = psycopg.errors.lookup(sqlstate)

    class _WithDiag(base):  # type: ignore[valid-type,misc]
        """진짜 오류는 서버 응답에서 진단을 읽는다. 여기서는 기본 문장만 흉내 낸다."""

        @property
        def diag(self) -> Any:
            return type("Diag", (), {"message_primary": message})()

    exc: psycopg.Error = _WithDiag(message)
    return exc


class _Cursor:
    def __init__(self, row: Any) -> None:
        self.row = row

    def fetchone(self) -> Any:
        return self.row


@dataclass
class FakeConn:
    """실행한 문장과 정리 호출을 기록한다. `fail_on`의 문장 조각을 만나면 그 오류를 낸다."""

    row: Any = GOOD_ROW
    fail_on: dict[str, BaseException] = field(default_factory=dict)
    residual: bool = False
    rollback_error: BaseException | None = None
    sleep_on: dict[str, float] = field(default_factory=dict)
    executed: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    def execute(self, query: Any, params: Any = None) -> _Cursor:
        text = query if isinstance(query, str) else repr(query)
        self.executed.append(text)
        for piece, seconds in self.sleep_on.items():
            if piece in text:
                time.sleep(seconds)
        for piece, exc in self.fail_on.items():
            if piece in text:
                raise exc
        if "pg_roles" in text:
            return _Cursor(self.row)
        if "pg_namespace" in text:
            return _Cursor((self.residual,))
        return _Cursor(None)

    def rollback(self) -> None:
        self.calls.append("rollback")
        if self.rollback_error:
            raise self.rollback_error

    def commit(self) -> None:  # 불리면 안 된다
        self.calls.append("commit")

    def close(self) -> None:
        self.calls.append("close")

    def cancel_safe(self, timeout: float = 0) -> None:
        self.calls.append("cancel")


@dataclass
class FakeConnect:
    """첫 연결은 실행용, 두 번째는 잔여 확인용."""

    main: FakeConn = field(default_factory=FakeConn)
    check: FakeConn = field(default_factory=FakeConn)
    fail_main: BaseException | None = None
    fail_check: BaseException | None = None
    opened: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, url: str, **kwargs: Any) -> FakeConn:
        self.opened.append(kwargs)
        if len(self.opened) == 1:
            if self.fail_main:
                raise self.fail_main
            return self.main
        if self.fail_check:
            raise self.fail_check
        return self.check


def _run(connect: FakeConnect, sql: bytes = SQL, **limits: float) -> SqlValidation:
    return validate_sql(sql, settings=SETTINGS, limits=SandboxLimits(**limits), connect=connect)


def _states(result: SqlValidation) -> dict[str, str]:
    return {s.stage: s.state for s in result.stages}


def _stage(result: SqlValidation, name: str) -> StageResult:
    return next(s for s in result.stages if s.stage == name)


# ── 정상 흐름 ─────────────────────────────────────────────────────────


def test_all_five_stages_pass_and_the_sql_is_never_committed() -> None:
    connect = FakeConnect()
    result = _run(connect)

    assert result.state == "passed"
    assert set(_states(result).values()) == {"passed"}
    assert connect.main.calls == ["rollback", "close"]  # commit 없음
    assert connect.opened[0]["autocommit"] is False
    assert connect.opened[1]["autocommit"] is True  # 잔여 확인은 별도 연결


def test_statements_are_cut_by_parser_positions_and_run_one_by_one() -> None:
    connect = FakeConnect()
    _run(connect)
    user = [q for q in connect.main.executed if q.startswith(("CREATE TABLE", "ALTER TABLE"))]
    assert user == [
        'CREATE TABLE "p" ("a" integer NOT NULL, PRIMARY KEY ("a"))',
        'CREATE TABLE "c" ("a" integer)',
        'ALTER TABLE "c" ADD FOREIGN KEY ("a") REFERENCES "p" ("a")',
    ]


def test_schema_name_is_generated_and_search_path_is_fixed_before_user_sql() -> None:
    connect = FakeConnect()
    _run(connect)
    executed = connect.main.executed
    create = next(i for i, q in enumerate(executed) if "CREATE SCHEMA" in q)
    path = next(i for i, q in enumerate(executed) if "search_path" in q)
    limits = next(i for i, q in enumerate(executed) if "statement_timeout" in q)
    first_user = next(i for i, q in enumerate(executed) if q.startswith("CREATE TABLE"))
    assert create < path < limits < first_user
    assert SCHEMA_PREFIX in executed[create] and "pg_temp" in executed[path]
    # 잔여 확인은 같은 이름을 값으로 바인딩해 묻는다 (SQL에 이어 붙이지 않음)
    assert any("pg_namespace" in q for q in connect.check.executed)


def test_failed_allowed_check_never_connects_and_keeps_the_hash() -> None:
    connect = FakeConnect()
    bad = b"CREATE TABLE t (a integer);\nCOMMIT;"
    result = _run(connect, bad)
    assert result.state == "failed"
    assert connect.opened == []
    assert _states(result)["sandbox_execute"] == "not_run"
    assert result.sql_sha256 == __import__("hashlib").sha256(bad).hexdigest()


# ── SQL 결함 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sqlstate", ["42P01", "42830", "42804", "42P07", "22023", "42601", "0A000"]
)
def test_known_sql_defect_is_failed_with_statement_and_cleanup_still_runs(sqlstate: str) -> None:
    connect = FakeConnect(main=FakeConn(fail_on={"ALTER TABLE": _db_error(sqlstate, "no key")}))
    result = _run(connect)

    execute = _stage(result, "sandbox_execute")
    assert (result.state, execute.state) == ("failed", "failed")
    [problem] = execute.problems
    assert (problem.kind, problem.statement, problem.sqlstate) == ("execution_error", 2, sqlstate)
    assert "no key" in problem.detail  # SQL 결함은 DB의 기본 문장을 남긴다
    assert (_states(result)["rollback"], _states(result)["residual_check"]) == ("passed", "passed")
    assert connect.main.calls == ["rollback", "close"]


# ── 환경·장애 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sqlstate", "kind"),
    [
        ("42501", "environment"),
        ("57014", "timeout"),
        ("55P03", "lock_timeout"),
        ("08006", "connection"),
        ("57P01", "database"),
        ("53100", "database"),
        ("XX000", "database"),
    ],
)
def test_other_db_errors_are_error_and_hide_internal_messages(sqlstate: str, kind: str) -> None:
    secret = "password=hunter2 host=10.0.0.1"
    connect = FakeConnect(main=FakeConn(fail_on={"ALTER TABLE": _db_error(sqlstate, secret)}))
    result = _run(connect)

    execute = _stage(result, "sandbox_execute")
    assert (result.state, execute.state) == ("error", "error")
    [problem] = execute.problems
    assert (problem.kind, problem.sqlstate, problem.statement) == (kind, sqlstate, 2)
    assert secret not in result.model_dump_json()
    assert connect.main.calls == ["rollback", "close"]


def test_connection_failure_does_not_claim_rollback_or_residual() -> None:
    connect = FakeConnect(fail_main=psycopg.OperationalError("refused"))
    result = _run(connect)
    assert result.state == "error"
    assert _states(result) == {
        "parse": "passed",
        "allowed_sql": "passed",
        "sandbox_execute": "error",
        "rollback": "not_run",
        "residual_check": "not_run",
    }
    assert _stage(result, "sandbox_execute").problems[0].kind == "connection"


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ((17, "specton_sandbox", False, False, False, False), "주요 버전"),
        ((18, "specton_app", False, False, False, False), "앱 DB에 접속"),
        ((18, "specton_sandbox", True, False, False, False), "슈퍼유저"),
        ((18, "specton_sandbox", False, True, False, False), "DB 생성"),
        ((18, "specton_sandbox", False, False, True, False), "역할 생성"),
        ((18, "specton_sandbox", False, False, False, True), "앱 DB 접속 권한"),
        (None, "계정 정보"),
    ],
)
def test_unsafe_environment_stops_before_user_sql(row: Any, reason: str) -> None:
    connect = FakeConnect(main=FakeConn(row=row))
    result = _run(connect)
    execute = _stage(result, "sandbox_execute")
    assert (execute.state, execute.problems[0].kind) == ("error", "environment")
    assert reason in execute.problems[0].detail
    assert not any(q.startswith("CREATE TABLE") for q in connect.main.executed)
    assert connect.main.calls == ["rollback", "close"]


def test_setup_failure_is_environment_not_sql_defect() -> None:
    connect = FakeConnect(main=FakeConn(fail_on={"CREATE SCHEMA": _db_error("42501")}))
    result = _run(connect)
    execute = _stage(result, "sandbox_execute")
    assert (execute.state, execute.problems[0].kind) == ("error", "environment")


def test_rollback_failure_keeps_the_sql_defect_and_makes_the_whole_result_error() -> None:
    main = FakeConn(
        fail_on={"ALTER TABLE": _db_error("42830")},
        rollback_error=psycopg.OperationalError("gone"),
    )
    result = _run(FakeConnect(main=main))
    assert result.state == "error"
    assert _states(result)["sandbox_execute"] == "failed"  # 결함 기록은 남는다
    assert _states(result)["rollback"] == "error"
    assert _stage(result, "rollback").problems[0].kind == "rollback_failed"
    assert main.calls == ["rollback", "close"]  # 롤백이 실패해도 닫는다


def test_remaining_schema_is_reported_not_dropped() -> None:
    connect = FakeConnect(check=FakeConn(residual=True))
    result = _run(connect)
    assert result.state == "error"
    assert _stage(result, "residual_check").problems[0].kind == "residual_found"
    assert not any("DROP" in q for q in connect.main.executed + connect.check.executed)


@pytest.mark.parametrize("where", ["connect", "query"])
def test_residual_check_failure_is_not_passed(where: str) -> None:
    if where == "connect":
        connect = FakeConnect(fail_check=psycopg.OperationalError("refused"))
    else:
        connect = FakeConnect(check=FakeConn(fail_on={"pg_namespace": _db_error("57P01")}))
    result = _run(connect)
    assert result.state == "error"
    assert _stage(result, "residual_check").problems[0].kind == "residual_check_failed"


def test_unexpected_exception_during_user_sql_is_internal_and_cleaned_up() -> None:
    connect = FakeConnect(main=FakeConn(fail_on={"ALTER TABLE": RuntimeError("bug")}))
    result = _run(connect)
    execute = _stage(result, "sandbox_execute")
    assert (execute.state, execute.problems[0].kind) == ("error", "internal")
    assert connect.main.calls == ["rollback", "close"]


# ── 전체 시간 예산 ────────────────────────────────────────────────────


def test_budget_timer_cancels_and_is_reported_as_budget_exceeded() -> None:
    """타이머가 울린 뒤 들어온 57014는 statement_timeout이 아니라 전체 예산 초과다."""

    class SlowThenCanceled(FakeConn):
        def execute(self, query: Any, params: Any = None) -> _Cursor:
            if isinstance(query, str) and query.startswith("ALTER TABLE"):
                time.sleep(0.3)
                raise _db_error("57014")
            return super().execute(query, params)

    main = SlowThenCanceled()
    result = _run(FakeConnect(main=main), budget_seconds=0.1)
    execute = _stage(result, "sandbox_execute")
    assert (execute.state, execute.problems[0].kind) == ("error", "budget_exceeded")
    assert "cancel" in main.calls
    assert main.calls[-2:] == ["rollback", "close"]


def test_budget_checked_between_statements() -> None:
    main = FakeConn(sleep_on={'CREATE TABLE "p"': 0.3})
    result = _run(FakeConnect(main=main), budget_seconds=0.1)
    execute = _stage(result, "sandbox_execute")
    assert execute.problems[0].kind == "budget_exceeded"
    assert not any(q.startswith("ALTER TABLE") for q in main.executed)


def test_sql_classification_table_has_no_environment_codes() -> None:
    """권한·연결·취소·잠금 코드가 SQL 결함 표에 섞이면 환경 문제로 재작업이 돈다."""
    assert not set(sandbox._SQL_DEFECTS) & {"42501", "57014", "55P03", "08006", "3D000"}


# ── 취소와 정리의 동기화 (검토 반영) ─────────────────────────────────


class _SlowCancel(FakeConn):
    """취소 요청이 오래 걸리는 연결. 취소 시작·끝과 롤백 순서를 기록한다."""

    def __init__(self, cancel_seconds: float, statement_seconds: float) -> None:
        super().__init__()
        self.cancel_seconds = cancel_seconds
        self.statement_seconds = statement_seconds

    def execute(self, query: Any, params: Any = None) -> _Cursor:
        if isinstance(query, str) and query.startswith("ALTER TABLE"):
            time.sleep(self.statement_seconds)
            raise _db_error("57014")  # 취소로 끊긴 문장
        return super().execute(query, params)

    def cancel_safe(self, timeout: float = 0) -> None:
        self.calls.append("cancel:start")
        time.sleep(self.cancel_seconds)
        self.calls.append("cancel:end")


def test_rollback_waits_for_a_cancel_already_in_progress() -> None:
    """타이머가 취소를 보내는 중에 문장이 끝나도, 취소가 끝난 뒤에 롤백·닫기를 한다."""
    main = _SlowCancel(cancel_seconds=0.4, statement_seconds=0.1)
    result = _run(FakeConnect(main=main), budget_seconds=0.05, connect_seconds=2)

    assert main.calls == ["cancel:start", "cancel:end", "rollback", "close"]
    execute = _stage(result, "sandbox_execute")
    assert (execute.state, execute.problems[0].kind) == ("error", "budget_exceeded")


def test_cancel_that_never_settles_hands_cleanup_over_without_overlap() -> None:
    """취소 요청이 기다림 한도(취소 제한+1초)를 넘으면 같은 연결로 바로 롤백·닫기를 하지 않는다.

    연결을 취소 스레드에 넘겨, 취소가 끝난 뒤에 롤백·닫기를 한다. 결과에는 정리를 확인하지
    못했다고 남기고(롤백 `error`), 잔여 확인은 하지 않는다. 어느 것도 통과로 쓰지 않는다.
    """
    main = _SlowCancel(cancel_seconds=1.6, statement_seconds=0.1)
    connect = FakeConnect(main=main)
    result = _run(connect, budget_seconds=0.05, connect_seconds=0.1)

    # 결과를 돌려준 시점: 취소는 아직 진행 중이고, 이 스레드는 연결을 건드리지 않았다
    assert main.calls == ["cancel:start"]
    execute = _stage(result, "sandbox_execute")
    assert (execute.state, execute.problems[0].kind) == ("error", "database")
    rollback = _stage(result, "rollback")
    assert (rollback.state, rollback.problems[0].kind) == ("error", "rollback_failed")
    assert _stage(result, "residual_check").state == "not_run"
    assert len(connect.opened) == 1  # 잔여 확인 연결을 열지 않음
    assert result.state == "error"

    # 취소가 끝나면 취소 스레드가 이어서 정리한다. 겹치지 않고 이 순서다
    deadline = time.monotonic() + 3
    while "close" not in main.calls and time.monotonic() < deadline:
        time.sleep(0.05)
    assert main.calls == ["cancel:start", "cancel:end", "rollback", "close"]


def test_handover_is_refused_once_the_cancel_has_finished() -> None:
    """취소가 이미 끝났으면 정리를 넘기지 않고, 호출한 쪽이 바로 정리한다."""
    conn = FakeConn()
    budget = sandbox._BudgetTimer(conn, SandboxLimits(budget_seconds=60))
    budget._cancel()  # 취소가 시작돼 끝남
    ran: list[str] = []
    assert budget.defer(lambda: ran.append("cleanup")) is False
    assert ran == []


def test_timer_callback_after_stop_does_nothing() -> None:
    conn = FakeConn()
    budget = sandbox._BudgetTimer(conn, SandboxLimits(budget_seconds=60))
    budget.start()
    assert budget.stop() is True
    budget._cancel()  # 늦게 도착한 콜백
    assert "cancel" not in conn.calls
    assert not budget.fired.is_set()


class _NeverFires:
    """콜백이 지연돼 아직 울리지 않은 타이머."""

    def __init__(self, seconds: float, function: Any) -> None:
        self.daemon = False

    def start(self) -> None: ...

    def cancel(self) -> None: ...

    def is_alive(self) -> bool:
        return False

    def join(self, timeout: float | None = None) -> None: ...


def test_deadline_is_checked_after_the_last_statement_even_if_the_timer_is_late(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """마지막 문장이 마감 뒤에 끝났는데 타이머 콜백이 아직 안 돌았어도 통과가 아니다."""
    monkeypatch.setattr(sandbox.threading, "Timer", _NeverFires)
    main = FakeConn(sleep_on={"ALTER TABLE": 0.2})
    result = _run(FakeConnect(main=main), budget_seconds=0.1)

    execute = _stage(result, "sandbox_execute")
    assert (execute.state, execute.problems[0].kind) == ("error", "budget_exceeded")
    assert execute.problems[0].statement is None  # 모든 문장을 실행한 뒤에 확인함
    assert result.state == "error"
    assert main.calls == ["rollback", "close"]


# R1 #171: libpq의 dbname 우선순위·디코딩을 사전 검사에도 적용한다.
@pytest.mark.parametrize("suffix", ["/review_path?dbname=specton_app", "/specton%5Fapp"])
@pytest.mark.parametrize("same_database", [True, False])
def test_effective_app_db_name_blocks_same_db_and_connect_permission(
    suffix: str, same_database: bool
) -> None:
    settings = Settings(
        _env_file=None, app_database_url="postgresql://review_user@localhost" + suffix
    )

    class PermissionConn(FakeConn):
        def execute(self, query: Any, params: Any = None) -> _Cursor:
            if isinstance(query, str) and "pg_roles" in query:
                # 실제 SQL에서 이름이 다르면 CONNECT 조회도 false가 되는 우회 사례를 재현한다.
                assert params == ("specton_app",)
                current = "specton_app" if same_database else "specton_sandbox"
                self.row = (18, current, False, False, False, params[0] == "specton_app")
            return super().execute(query, params)

    connect = FakeConnect(main=PermissionConn())
    result = validate_sql(SQL, settings=settings, connect=connect)
    problem = _stage(result, "sandbox_execute").problems[0]
    assert (result.state, problem.kind) == ("error", "environment")
    assert ("앱 DB에 접속함" if same_database else "앱 DB 접속 권한") in problem.detail
    assert not any("CREATE SCHEMA" in q or "CREATE TABLE" in q for q in connect.main.executed)
    assert connect.main.calls == ["rollback", "close"]


@pytest.mark.parametrize("suffix", ["", "/", "/?dbname="])
def test_missing_app_db_name_is_environment_error_without_connecting(suffix: str) -> None:
    settings = Settings(
        _env_file=None,
        app_database_url="postgresql://review_user:private_password@localhost" + suffix,
    )
    connect = FakeConnect()
    result = validate_sql(SQL, settings=settings, connect=connect)
    assert result.state == "error"
    assert _stage(result, "sandbox_execute").problems[0].kind == "environment"
    assert _states(result)["rollback"] == _states(result)["residual_check"] == "not_run"
    assert connect.opened == []
    assert "private_password" not in result.model_dump_json()
    assert "review_user" not in result.model_dump_json()


def test_invalid_conninfo_is_rejected_without_exposing_parser_message(monkeypatch: Any) -> None:
    def invalid(url: str) -> Any:
        raise psycopg.ProgrammingError("private_password in invalid DSN")

    monkeypatch.setattr(sandbox, "conninfo_to_dict", invalid)
    connect = FakeConnect()
    result = _run(connect)
    assert result.state == "error"
    assert _stage(result, "sandbox_execute").problems[0].kind == "environment"
    assert connect.opened == []
    assert "private_password" not in result.model_dump_json()
