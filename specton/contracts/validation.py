"""SQL 검증 결과 (#167, 05 문서).

검증기(#15)가 만들고, 실행기(#17)가 체크포인트에 담고, 저장·승인 검사가 읽는 공용 결과다.

- 검증은 다섯 단계를 순서대로 한다: 파싱 → 허용 문장 검사 → 격리 DB 실행 → 롤백 → 잔여 객체 확인.
  결과에는 다섯 단계가 순서대로 한 번씩 있다. 실행하지 않은 단계는 `not_run`으로 남긴다.
- 전체 상태는 단계 결과로 정해진다(`overall_status`). 계약이 둘이 맞는지 검사한다.
- run·revision·`model_hash`·검증 시도 ID는 검증기가 모른다. 실행기·저장 쪽이 붙인다.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from specton.contracts.base import Contract, NonEmptyText

# 검증한 SQL 바이트의 SHA-256 (16진수 소문자). `ArtifactRef.hash`와 같은 계산이다.
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
# PostgreSQL 오류 코드 (숫자·대문자 5자리, 예: 42601)
SqlState = Annotated[str, StringConstraints(pattern=r"^[0-9A-Z]{5}$")]


class ValidationStepName(StrEnum):
    """검증 단계. 정의 순서가 실행 순서다."""

    PARSE = "parse"
    ALLOWED_STATEMENTS = "allowed_statements"
    EXECUTE = "execute"  # 격리 DB에서 실행
    ROLLBACK = "rollback"
    CLEANUP = "cleanup"  # 남은 객체가 없는지 확인


VALIDATION_STEPS: tuple[ValidationStepName, ...] = tuple(ValidationStepName)


class StepStatus(StrEnum):
    """단계 결과. `failed`는 SQL 결함, `error`는 검증 환경·정리 장애다.

    롤백·잔여 객체 확인은 SQL 결함을 판정하지 않으므로 `failed`가 없다. 실패하거나 끝났는지
    확인하지 못하면 `error`다 (#167 R1 기준 2).
    """

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    NOT_RUN = "not_run"


class ValidationStatus(StrEnum):
    """전체 결과. 최종 승인 근거가 되는 것은 `passed`뿐이다 (#167).

    `unverified`는 실패는 없지만 실행하지 않은 단계가 있는 결과다(예: 파싱·허용 검사까지만 한 경우).
    """

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    UNVERIFIED = "unverified"


class ValidationIssue(Contract):
    """단계에서 나온 문제 한 건.

    `message`에는 사용자에게 보여도 되는 문장만 넣는다. 접속 정보·내부 경로·예외 원문은 넣지 않는다.
    """

    code: NonEmptyText  # 짧은 원인 코드 (예: syntax_error, forbidden_statement)
    message: NonEmptyText | None = None
    statement_index: int | None = Field(default=None, ge=0)  # 문제가 난 SQL 문장 번호 (0부터)
    sqlstate: SqlState | None = None


# 결과가 `failed`일 수 없는 정리 단계
_CLEANUP_STEPS = frozenset({ValidationStepName.ROLLBACK, ValidationStepName.CLEANUP})


class ValidationStep(Contract):
    """단계 결과 한 건. `failed`·`error`는 문제가 1건 이상, `passed`·`not_run`은 문제가 없다."""

    name: ValidationStepName
    status: StepStatus
    issues: tuple[ValidationIssue, ...] = ()

    @model_validator(mode="after")
    def _check_issues(self) -> Self:
        if self.name in _CLEANUP_STEPS and self.status is StepStatus.FAILED:
            raise ValueError(f"{self.name}: 정리 단계의 실패는 error로 적습니다")
        if self.status in (StepStatus.FAILED, StepStatus.ERROR) and not self.issues:
            raise ValueError(f"{self.name}: {self.status} 단계에는 문제가 1건 이상 있어야 합니다")
        if self.status in (StepStatus.PASSED, StepStatus.NOT_RUN) and self.issues:
            raise ValueError(f"{self.name}: {self.status} 단계에는 문제를 두지 않습니다")
        return self


def overall_status(steps: Iterable[ValidationStep]) -> ValidationStatus:
    """단계 결과로 전체 상태를 정한다. `error` > `failed` > `unverified` > `passed` 순이다.

    SQL 결함과 정리 장애가 함께 있으면 `error`다. 정리를 확인하지 못하면 격리 DB 상태를 믿을 수 없기
    때문이다. 결함은 그 단계의 `issues`에 그대로 남는다 (#167).
    """
    statuses = {step.status for step in steps}
    if StepStatus.ERROR in statuses:
        return ValidationStatus.ERROR
    if StepStatus.FAILED in statuses:
        return ValidationStatus.FAILED
    if StepStatus.NOT_RUN in statuses or not statuses:
        return ValidationStatus.UNVERIFIED
    return ValidationStatus.PASSED


class SqlValidation(Contract):
    """SQL 파일 하나의 검증 결과.

    `artifact_hash`는 검증한 바이트의 해시다. 저장할 때 산출물 해시와 같아야 한다.
    버전 셋은 승인 검사가 「지금 요구하는 기준」과 비교한다 (#167).
    """

    status: ValidationStatus
    artifact_hash: Sha256Hex
    validator_version: NonEmptyText
    policy_version: NonEmptyText
    postgres_version: (
        NonEmptyText  # 대상 DB. DDL 생성기의 `DDL_TARGET`과 같은 값 (예: postgresql-18)
    )
    steps: tuple[ValidationStep, ...]

    @model_validator(mode="after")
    def _check_steps(self) -> Self:
        names = tuple(step.name for step in self.steps)
        if names != VALIDATION_STEPS:
            raise ValueError(
                f"다섯 단계가 순서대로 한 번씩 있어야 합니다: {[str(n) for n in names]}"
            )
        by_name = {step.name: step.status for step in self.steps}
        checked = (ValidationStepName.PARSE, ValidationStepName.ALLOWED_STATEMENTS)
        if by_name[ValidationStepName.EXECUTE] is not StepStatus.NOT_RUN and any(
            by_name[name] is not StepStatus.PASSED for name in checked
        ):
            raise ValueError("파싱·허용 문장 검사를 통과하지 않은 SQL은 실행하지 않습니다")
        expected = overall_status(self.steps)
        if self.status is not expected:
            raise ValueError(
                f"전체 상태가 단계 결과와 다릅니다: {self.status} (단계 기준 {expected})"
            )
        return self
