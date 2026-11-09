"""PostgreSQL 18 타입 매개변수 상한 (#255). DDL 생성기와 A03 출력 검사가 함께 쓴다.

DDL 생성기(`codegen/ddl.py`)는 상한을 넘는 값을 고치지 않고 멈추는 마지막 방어선이고,
A03은 같은 상한으로 LLM 출력을 먼저 검사해 재요청한다. 이 모듈은 다른 specton 모듈을
import하지 않아 `nodes/`와 `codegen/` 어느 쪽에서 가져다 써도 의존 방향 규칙을 지킨다
(`specton/ids.py`와 같은 방식).
"""

# 넘으면 파싱은 되지만 실행에서 22023 오류로 거절된다.
MAX_CHAR_LENGTH = 10485760  # char·varchar length (PostgreSQL 18 문서 8.3)
MAX_NUMERIC_PRECISION = 1000  # 명시적 numeric precision (PostgreSQL 18 문서 8.1.2)


def type_limit_problems(length: int | None, precision: int | None) -> list[str]:
    """상한을 넘는 매개변수 설명. 넘지 않으면 빈 목록이다.

    타입과 매개변수의 조합(예: numeric에 length)은 계약(`AttributeDraft`)이 먼저 거른다.
    여기서는 값의 크기만 본다. 어느 객체인지는 부르는 쪽이 메시지 앞에 붙인다.
    """
    problems = []
    if length is not None and length > MAX_CHAR_LENGTH:
        problems.append(f"length는 {MAX_CHAR_LENGTH} 이하여야 합니다 ({length})")
    if precision is not None and precision > MAX_NUMERIC_PRECISION:
        problems.append(f"precision은 {MAX_NUMERIC_PRECISION} 이하여야 합니다 ({precision})")
    return problems
