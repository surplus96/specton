"""SQL 검증 결과 계약 (#175, #167)."""

import hashlib

import pytest
from pydantic import ValidationError

from specton.contracts import (
    VALIDATION_STEPS,
    SqlValidation,
    StepStatus,
    ValidationIssue,
    ValidationStatus,
    ValidationStep,
    ValidationStepName,
    overall_status,
)

PARSE, ALLOWED, EXECUTE, ROLLBACK, CLEANUP = VALIDATION_STEPS
HASH = hashlib.sha256(b"CREATE TABLE t (id integer);").hexdigest()


def _step(name: ValidationStepName, status: str = "passed") -> ValidationStep:
    issues = () if status in ("passed", "not_run") else (ValidationIssue(code=f"{name}_{status}"),)
    return ValidationStep(name=name, status=status, issues=issues)


def _steps(**statuses: str) -> tuple[ValidationStep, ...]:
    """지정하지 않은 단계는 `passed`."""
    return tuple(_step(name, statuses.get(name, "passed")) for name in VALIDATION_STEPS)


def _validation(steps: tuple[ValidationStep, ...], status: str | None = None) -> SqlValidation:
    return SqlValidation(
        status=status or overall_status(steps),
        artifact_hash=HASH,
        validator_version="sql-validator-v1",
        policy_version="allowed-sql-v1",
        postgres_version="postgresql-18",
        steps=steps,
    )


def test_steps_run_in_the_agreed_order() -> None:
    assert [str(name) for name in VALIDATION_STEPS] == [
        "parse",
        "allowed_statements",
        "execute",
        "rollback",
        "cleanup",
    ]


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ({}, "passed"),
        ({"execute": "not_run", "rollback": "not_run", "cleanup": "not_run"}, "unverified"),
        ({"execute": "failed"}, "failed"),
        ({"parse": "failed", "allowed_statements": "not_run", "execute": "not_run"}, "failed"),
        ({"cleanup": "error"}, "error"),
        # SQL 결함과 정리 장애가 함께면 error. 결함은 단계에 남는다 (#167 R1 기준 2)
        ({"execute": "failed", "rollback": "error", "cleanup": "not_run"}, "error"),
        ({"execute": "failed", "cleanup": "error"}, "error"),
    ],
)
def test_overall_status_follows_the_steps(statuses: dict[str, str], expected: str) -> None:
    result = _validation(_steps(**statuses))

    assert result.status == ValidationStatus(expected)
    if statuses.get("execute") == "failed":
        assert result.steps[2].status is StepStatus.FAILED
        assert result.steps[2].issues


def test_status_that_disagrees_with_the_steps_is_rejected() -> None:
    steps = _steps(execute="not_run", rollback="not_run", cleanup="not_run")

    with pytest.raises(ValidationError, match="전체 상태가 단계 결과와 다릅니다"):
        _validation(steps, status="passed")


@pytest.mark.parametrize(
    "names",
    [
        (PARSE, ALLOWED, EXECUTE, ROLLBACK),  # 누락
        (PARSE, ALLOWED, EXECUTE, ROLLBACK, CLEANUP, CLEANUP),  # 중복
        (ALLOWED, PARSE, EXECUTE, ROLLBACK, CLEANUP),  # 순서
        (),
    ],
)
def test_all_five_steps_are_required_once_in_order(names: tuple[ValidationStepName, ...]) -> None:
    steps = tuple(_step(name) for name in names)

    with pytest.raises(ValidationError, match="다섯 단계"):
        _validation(steps, status="passed")


@pytest.mark.parametrize("before", ["failed", "error", "not_run"])
def test_sql_is_not_executed_before_it_passes_the_checks(before: str) -> None:
    steps = _steps(allowed_statements=before)

    with pytest.raises(ValidationError, match="실행하지 않습니다"):
        _validation(steps)


def test_cleanup_is_kept_after_a_failed_execution() -> None:
    """실행이 실패해도 실제로 시도한 정리 결과를 남긴다."""
    result = _validation(_steps(execute="failed"))

    assert [s.status for s in result.steps[3:]] == [StepStatus.PASSED, StepStatus.PASSED]


@pytest.mark.parametrize("status", ["failed", "error"])
def test_failed_or_error_step_needs_an_issue(status: str) -> None:
    with pytest.raises(ValidationError, match="문제가 1건 이상"):
        ValidationStep(name=EXECUTE, status=status)


@pytest.mark.parametrize("status", ["passed", "not_run"])
def test_passed_or_not_run_step_has_no_issue(status: str) -> None:
    with pytest.raises(ValidationError, match="문제를 두지 않습니다"):
        ValidationStep(name=EXECUTE, status=status, issues=(ValidationIssue(code="x"),))


def test_issue_fields() -> None:
    issue = ValidationIssue(
        code="syntax_error", message="2번째 문장 문법 오류", statement_index=1, sqlstate="42601"
    )

    assert issue.statement_index == 1
    with pytest.raises(ValidationError):
        ValidationIssue(code="x", statement_index=-1)
    with pytest.raises(ValidationError):
        ValidationIssue(code="x", sqlstate="4260")
    with pytest.raises(ValidationError):
        ValidationIssue(code="")


@pytest.mark.parametrize("value", ["", HASH.upper(), HASH[:-1], "sha256:" + HASH])
def test_artifact_hash_is_lowercase_sha256_hex(value: str) -> None:
    steps = _steps()

    with pytest.raises(ValidationError):
        SqlValidation(
            status="passed",
            artifact_hash=value,
            validator_version="v",
            policy_version="p",
            postgres_version="postgresql-18",
            steps=steps,
        )


@pytest.mark.parametrize("field", ["validator_version", "policy_version", "postgres_version"])
def test_versions_are_required(field: str) -> None:
    with pytest.raises(ValidationError):
        _validation(_steps()).evolve(**{field: ""})


@pytest.mark.parametrize("name", [ROLLBACK, CLEANUP])
def test_cleanup_steps_report_errors_not_failures(name: ValidationStepName) -> None:
    """롤백·잔여 확인 실패는 SQL 결함이 아니라 장애다 (#167 R1 기준 2)."""
    with pytest.raises(ValidationError, match="error로 적습니다"):
        ValidationStep(name=name, status="failed", issues=(ValidationIssue(code="x"),))
