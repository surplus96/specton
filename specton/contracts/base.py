"""계약 공통 요소: 기본 모델, 열거형, ID 형식, 원문 위치 (05 문서)."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class Contract(BaseModel):
    """모든 계약 모델의 기반. 불변이며, 알 수 없는 필드는 거절하고 앞뒤 공백을 제거한다.

    값을 바꿀 때는 `model_copy(update=...)`로 새 객체를 만든다. 목록 필드는 tuple이다.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# 내부 요구사항 ID는 코드가 부여한다. 기능·엔티티·관계 ID 규칙은 #12(모델 정리)가 정하므로
# 여기서는 비어 있지 않은 문자열만 요구한다.
ReqId = Annotated[str, StringConstraints(pattern=r"^REQ-\d{2,}$")]
EntityId = Annotated[str, StringConstraints(min_length=1, max_length=64)]
ObjectId = Annotated[str, StringConstraints(min_length=1, max_length=64)]
NonEmptyText = Annotated[str, StringConstraints(min_length=1)]
# 표 안 셀 위치. 엑셀 셀 주소 형식(열 문자 + 1부터 시작하는 행 번호)이다.
CellAddress = Annotated[str, StringConstraints(pattern=r"^[A-Z]+[1-9][0-9]*$")]


class Priority(StrEnum):
    """MoSCoW (ADR-0006). 임의 문자열은 넣지 않고 미정은 null로 둔다."""

    MUST = "Must"
    SHOULD = "Should"
    COULD = "Could"
    WONT = "Won't"


class PrioritySource(StrEnum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    UNSPECIFIED = "unspecified"


class RequirementType(StrEnum):
    FR = "FR"
    NFR = "NFR"


class NfrCategory(StrEnum):
    """비기능 분류 (05 문서, ADR-0009). 데이터 정합성 요구는 FR로 분류한다."""

    SECURITY = "security"
    AUDIT = "audit"
    RETENTION = "retention"
    PERFORMANCE = "performance"
    AVAILABILITY = "availability"
    USABILITY = "usability"
    OTHER = "other"


class SqlType(StrEnum):
    """허용 SQL 타입. `domain_packs/common/domains.yaml`의 allowed_sql_types와 같아야 한다."""

    CHAR = "char"
    VARCHAR = "varchar"
    TEXT = "text"
    NUMERIC = "numeric"
    INTEGER = "integer"
    BIGINT = "bigint"
    BOOLEAN = "boolean"
    DATE = "date"
    TIME = "time"
    TIMESTAMP = "timestamp"
    TIMESTAMPTZ = "timestamptz"


class Crud(StrEnum):
    CREATE = "C"
    READ = "R"
    UPDATE = "U"
    DELETE = "D"


class Cardinality(StrEnum):
    ONE_TO_ONE = "1:1"
    ONE_TO_MANY = "1:N"
    MANY_TO_MANY = "N:M"


class TargetStage(StrEnum):
    """재작업 복귀 단계. `relationships` 단독 값은 없다 (03 문서)."""

    REQUIREMENTS = "requirements"
    FUNCTIONS = "functions"
    DATA_MODEL = "data_model"


class ExtractionStatus(StrEnum):
    OK = "ok"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class SourceRef(Contract):
    """원문 위치. 문자열 인코딩 대신 구조체로 둔다 (ADR-0009).

    형식별 필수 필드:
    - xlsx: sheet, row
    - csv: row
    - pdf: page, block
    - hwpx: section, paragraph (표 안이면 table, cell도)
    """

    kind: Literal["xlsx", "csv", "pdf", "hwpx"]
    sheet: str | None = None
    row: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1)
    block: int | None = Field(default=None, ge=0)
    section: int | None = Field(default=None, ge=0)
    paragraph: int | None = Field(default=None, ge=0)
    table: int | None = Field(default=None, ge=0)
    cell: CellAddress | None = None

    @model_validator(mode="after")
    def _check_locator(self) -> Self:
        required: dict[str, tuple[str, ...]] = {
            "xlsx": ("sheet", "row"),
            "csv": ("row",),
            "pdf": ("page", "block"),
            "hwpx": ("section", "paragraph"),
        }
        missing = [f for f in required[self.kind] if getattr(self, f) is None]
        if missing:
            raise ValueError(
                f"{self.kind} 원문 위치에 필요한 필드가 없습니다: {', '.join(missing)}"
            )
        if (self.table is None) != (self.cell is None):
            raise ValueError("table과 cell은 함께 지정합니다")
        return self

    def display(self) -> str:
        """사람이 읽는 표기. 저장·비교에는 구조체를 쓴다."""
        match self.kind:
            case "xlsx":
                return f"{self.sheet}!{self.row}행"
            case "csv":
                return f"{self.row}행"
            case "pdf":
                return f"{self.page}쪽 블록{self.block}"
            case "hwpx":
                where = f"구역{self.section} 문단{self.paragraph}"
                if self.table is not None:
                    where += f" 표{self.table} {self.cell}"
                return where
