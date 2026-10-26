"""실행 제어 API 계약: run 상태·resume 응답·SSE 이벤트·오류 (06 문서).

`docs/api/openapi.json`의 같은 이름 스키마와 필드·열거값이 같아야 한다
(tests/unit/test_contracts_api.py).
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field

from specton.contracts.base import Contract, NonEmptyText
from specton.contracts.state import RunState


class ErrorCode(StrEnum):
    """오류 코드 후보. 목록은 계약 동결 때 확정한다 (06 문서)."""

    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    RUN_REVISION_CONFLICT = "RUN_REVISION_CONFLICT"
    INTERRUPT_STALE = "INTERRUPT_STALE"
    EVENT_REPLAY_EXPIRED = "EVENT_REPLAY_EXPIRED"
    ARTIFACT_NOT_READY = "ARTIFACT_NOT_READY"
    ARTIFACT_FORMAT_UNSUPPORTED = "ARTIFACT_FORMAT_UNSUPPORTED"
    UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    PACK_UNSUPPORTED = "PACK_UNSUPPORTED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    INTERNAL = "INTERNAL"


class Error(Contract):
    """모든 오류 응답의 공통 형식. 파일 경로·비밀값·내부 예외를 담지 않는다."""

    code: str  # ErrorCode 값. 확장 가능성 때문에 응답에서는 문자열로 받는다
    message: NonEmptyText
    run_id: str | None = None
    retryable: bool


class InterruptKind(StrEnum):
    EXTRACTION = "extraction"
    REQUIREMENTS = "requirements"
    REVIEW = "review"


class Interrupt(Contract):
    interrupt_id: NonEmptyText
    kind: InterruptKind
    message: NonEmptyText


class RunStatus(Contract):
    run_id: UUID
    status: RunState
    revision: int = Field(ge=0)
    stage: str | None = None
    interrupt: Interrupt | None = None
    error: Error | None = None


class RunSummary(Contract):
    run_id: UUID
    status: RunState
    revision: int = Field(ge=0)
    created_at: datetime


class ExtractionEdit(Contract):
    block_id: NonEmptyText
    text: str


class ExtractionResponse(Contract):
    kind: Literal["extraction"]
    confirmed: bool
    edits: list[ExtractionEdit]


class RequirementAnswer(Contract):
    req_id: NonEmptyText
    action: Literal["keep", "edit", "split"]
    texts: list[str]


class RequirementsResponse(Contract):
    kind: Literal["requirements"]
    answers: list[RequirementAnswer]


class ReviewResponse(Contract):
    kind: Literal["review"]
    decision: Literal["approve", "revise", "hold"]
    feedback: str


ResumeResponse = Annotated[
    ExtractionResponse | RequirementsResponse | ReviewResponse, Field(discriminator="kind")
]


class ResumeRequest(Contract):
    interrupt_id: NonEmptyText
    expected_revision: int = Field(ge=0)
    response: ResumeResponse


class RunView(Contract):
    """화면용 읽기 모델. 항목의 세부 구조는 섹션별로 설계 모델(design.py)을 직렬화해 쓴다."""

    run_id: UUID
    revision: int = Field(ge=0)
    section: Literal["extraction", "requirements", "design", "review"]
    items: list[dict[str, Any]]
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class SseEventType(StrEnum):
    STATUS = "status"
    INTERRUPT = "interrupt"
    ARTIFACT = "artifact"
    ERROR = "error"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SseEventData(Contract):
    """SSE `data` 본문. 원문 전체와 비밀값은 넣지 않는다."""

    run_id: str
    revision: int = Field(ge=0)
    stage: str | None = None
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)


class SseEvent(Contract):
    """SSE 한 건. `id`는 run 안에서 단조 증가하며 `Last-Event-ID` 재생 기준이다."""

    id: int = Field(ge=1)
    event: SseEventType
    data: SseEventData

    def encode(self) -> str:
        return f"id: {self.id}\nevent: {self.event.value}\ndata: {self.data.model_dump_json()}\n\n"
