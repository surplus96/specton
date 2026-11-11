"""모델 정리(#12) 코드가 쓰는 결과 모델과 줄임 함수.

결과 형식은 계약(`specton.contracts.normalized`)으로 옮겼다 (#142). 정리 코드와 시험의 import를
그대로 두려고 같은 이름을 여기서 다시 내보낸다. 이 모듈은 LLM client를 import하지 않는다.
"""

from specton.contracts.normalized import (
    Column,
    ForeignKey,
    Normalized,
    NormalizedModel,
    NormalizeFailed,
    NormalizeResult,
    Problem,
    ProblemCode,
    Table,
)

__all__ = [
    "RULES_VERSION",
    "Column",
    "ForeignKey",
    "NormalizeFailed",
    "NormalizeResult",
    "Normalized",
    "NormalizedModel",
    "Problem",
    "ProblemCode",
    "Table",
    "problem",
]

# 정리 규칙 버전. 규칙(FK 이름·ID 계산 등)이 바뀌면 올린다. 임시 값이다.
RULES_VERSION = "normalize-v4"


def problem(
    code: ProblemCode,
    target: str,
    detail: str,
    *,
    decision: str | None = None,
    pending: bool = False,
) -> Problem:
    """`Problem`을 위치 인자로 만드는 줄임 함수."""
    return Problem(code=code, target=target, detail=detail, decision=decision, pending=pending)
