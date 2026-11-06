"""모델 정리(#12) 결과 모델. **임시**이며 공용 계약(`specton/contracts/`)이 아니다.

A03 엔티티·속성과 A04 관계를 테이블·컬럼·PK·FK로 바꾼 결과를 담는다. ERD(#13)·RTM(#14)·DDL(#15)이
같은 결과를 쓰도록, 모양이 정해지면 #12에 공유하고 팀 확인을 받는다 (R4 제안, #12 확인 전).

- PK·FK·UNIQUE는 모두 컬럼 ID 묶음(순서 있음)이다. 한 칸짜리도 묶음 하나다.
- 결과는 성공(`Normalized`)과 실패(`NormalizeFailed`)를 타입으로 나눈다. 문제가 하나라도 있으면
  결과 모델을 내지 않아, 후속 생성이 불완전한 모델을 성공으로 받지 않는다.
- 이 모듈은 LLM client를 import하지 않는다 (CLAUDE.md, `codegen/` 규칙).
- 모양은 불변 Pydantic 모델이다. 그래프 체크포인트에 저장했다 꺼내도 같은 값으로 돌아오게 하려는
  것이다(검증을 다시 거치며 목록이 tuple로 돌아온다). 결과를 어디에 담을지는 정하지 않았다 (D9).
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from specton.contracts.base import SqlType

# 정리 규칙 버전. 규칙(FK 이름·ID 계산 등)이 바뀌면 올린다. 임시 값이다.
RULES_VERSION = "normalize-v0"


class _Frozen(BaseModel):
    """정리 결과 모델의 기반. 불변이며 알 수 없는 필드를 거절한다. 계약(`Contract`)과는 별개다."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ProblemCode(StrEnum):
    """정리를 막는 문제의 종류."""

    INPUT_TRACE = "input_trace"  # 입력 추적 위반 (계약의 find_trace_issues)
    PACK_MISMATCH = "pack_mismatch"  # 엔티티의 팩이 정리에 쓰는 팩과 다름
    NO_PRIMARY_KEY = "no_primary_key"  # RULE-03 PK 없음 (D6)
    PARENT_WITHOUT_KEY = "parent_without_key"  # 부모에 PK가 없어 FK를 만들 수 없음
    FK_COLUMN_CONFLICT = "fk_column_conflict"  # FK 칸 이름이 기존 칸과 겹침 (D4·D13)
    OPTIONAL_IDENTIFYING = "optional_identifying_conflict"  # 선택 관계인데 식별 관계 (D11)
    IDENTIFYING_CYCLE = "identifying_cycle"  # 식별 관계가 순환해 PK 순서를 정할 수 없음 (D14)
    NAMING_RULE_MISSING = "naming_rule_missing"  # 필요한 명명 규칙이 naming.yaml에 없음 (D4)
    UNRESOLVED_NAME = "unresolved_name"  # 팩 용어·사전으로 물리명을 만들 수 없음 (D5 결정 대기)
    NAME_TOO_LONG = "name_too_long"  # naming.yaml max_bytes 초과
    RESERVED_WORD = "reserved_word"  # 예약어와 같은 단독 이름
    DUPLICATE_NAME = "duplicate_name"  # 같은 물리명이 둘 이상
    UNSUPPORTED_RELATIONSHIP = "unsupported_relationship"  # 처리하지 않는 관계 유형
    REQUIRED_SELF_REFERENCE = "required_self_reference"  # 필수 자기참조: 최상위 행을 못 넣음
    DOMAIN_TYPE_MISMATCH = "domain_type_mismatch"  # 속성 타입 ≠ 같은 이름 팩 용어의 도메인 타입
    OUTPUT_TRACE = "output_trace"  # 결과 모델의 참조·ID·추적 위반 (코드 오류 방어)


class Problem(_Frozen):
    """정리 문제 한 건.

    `decision`은 관련 결정 번호(예: "D13")다. `pending`이 참이면 차단 여부가 아직 정해지지
    않은 문제다(D5). 지금은 결정 대기 문제도 결과를 막는다. 이름이 없으면 테이블을 완성할 수
    없기 때문이다.
    """

    code: ProblemCode
    target: str  # 문제가 난 객체 ID (엔티티·속성·관계·테이블·컬럼·FK)
    detail: str
    decision: str | None = None
    pending: bool = False


class Column(_Frozen):
    """테이블 컬럼. 속성에서 오면 `attribute_id`, 관계에서 파생된 FK 칸이면 `relationship_id`.

    출처는 둘 중 정확히 하나다. FK 칸은 `references`에 짝이 되는 부모 칸 ID를 남긴다.
    """

    id: str
    name: str  # 논리명 (한글)
    physical_name: str  # DDL에 쓰는 이름 (소문자)
    data_type: SqlType
    length: int | None
    precision: int | None  # numeric 전용
    scale: int | None
    time_precision: int | None  # 시각 타입의 소수 초 자릿수. 팩 도메인에서 온다 (#12 댓글 2)
    domain: str | None  # 팩 도메인 이름. DDL이 타입 프로필(strict/pg_native)을 고를 때 쓴다
    nullable: bool
    req_ids: tuple[str, ...]
    attribute_id: str | None = None
    relationship_id: str | None = None
    references: str | None = None  # FK 칸이 가리키는 부모 칸 ID


class Table(_Frozen):
    """테이블. 엔티티에서 오면 `entity_id`, N:M 연결 테이블이면 `relationship_id`를 갖는다.

    출처는 둘 중 정확히 하나다. 연결 테이블의 칸은 모두 그 관계에서 파생된 FK 칸이다.
    """

    id: str
    name: str
    physical_name: str
    columns: tuple[Column, ...]
    primary_key: tuple[str, ...]  # 컬럼 ID 묶음, 순서 있음
    unique_keys: tuple[tuple[str, ...], ...]  # 컬럼 ID 묶음들
    req_ids: tuple[str, ...]
    entity_id: str | None = None
    relationship_id: str | None = None


class ForeignKey(_Frozen):
    """FK. `columns[i]`가 부모의 `parent_columns[i]`를 가리킨다 (부모 PK 순서, D12)."""

    id: str
    relationship_id: str
    table_id: str  # 자식 테이블
    columns: tuple[str, ...]
    parent_table_id: str
    parent_columns: tuple[str, ...]
    req_ids: tuple[str, ...]


class NormalizedModel(_Frozen):
    """정리 결과. 객체는 ID 순으로 정렬해 같은 입력이면 같은 값이 된다.

    `lexicon_digest`는 물리명·도메인·이름 규칙을 읽은 팩 파일 내용의 해시다. 팩 버전 문자열만으로는
    내용이 같다는 보장이 없어(버전은 사람이 올림) 내용을 따로 남긴다.
    저장·재계산 방식(D9)은 미정이다.
    """

    pack: str
    pack_version: str
    rules_version: str
    lexicon_digest: str
    tables: tuple[Table, ...]
    foreign_keys: tuple[ForeignKey, ...]


class Normalized(_Frozen):
    """정리 성공."""

    model: NormalizedModel


class NormalizeFailed(_Frozen):
    """정리 실패. 문제 목록만 있고 결과 모델은 없다."""

    problems: tuple[Problem, ...]


NormalizeResult = Normalized | NormalizeFailed


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
