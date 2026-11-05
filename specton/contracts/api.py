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
    """오류 코드 (06 문서, ADR-0009). 응답의 `Error.code`는 확장을 위해 문자열로 받는다."""

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
    INVALID_REQUEST = "INVALID_REQUEST"  # resume 밖 요청의 형식 오류 (조회 조건 등)
    # 실행 실패 원인 (`RunStatus.error`). specton.llm 예외·문서 추출 실패와 대응한다.
    LLM_REFUSED = "LLM_REFUSED"
    LLM_OUTPUT_INVALID = "LLM_OUTPUT_INVALID"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    INTERNAL = "INTERNAL"


class Error(Contract):
    """모든 오류 응답의 공통 형식. 파일 경로·비밀값·내부 예외를 담지 않는다."""

    code: str  # ErrorCode 값. 확장 가능성 때문에 응답에서는 문자열로 받는다
    message: NonEmptyText
    run_id: str | None = None
    retryable: bool


class InterruptKind(StrEnum):
    """사람 확인(HITL) 지점. 값은 resume 응답의 `kind`와 같다 (05 문서 「모델별 `kind` 뜻」).

    - extraction: 추출 확인(UI-02). `review`·`fail` 블록이 있을 때만 멈춘다 (ADR-0015)
    - requirements: 분석 확인(HITL 1, UI-03). 품질 경고·질문·분할이 있을 때만 멈춘다 (ADR-0015)
    - review: 최종 검토(HITL 2, UI-06). 내보내기 전에 항상 멈춘다
    """

    EXTRACTION = "extraction"
    REQUIREMENTS = "requirements"
    REVIEW = "review"


class Interrupt(Contract):
    """대기 중인 확인 요청. 실행이 사람 확인에서 멈추면 `RunStatus.interrupt`에 담긴다.

    `interrupt_id`는 resume 요청에 그대로 돌려보낸다. 이미 답했거나 바뀐 요청이면 409
    `INTERRUPT_STALE`이다. `message`는 확인 종류별 고정 문구다.
    """

    interrupt_id: NonEmptyText
    kind: InterruptKind
    message: NonEmptyText


class RunStatus(Contract):
    """실행 한 건의 현재 상태. 등록·조회·재개·취소 응답이다 (06 문서).

    `stage`는 실행기가 마지막으로 저장한 단계다. `interrupt`는 사람 확인을 기다릴 때만,
    `error`는 실패했을 때만 있다.
    """

    run_id: UUID
    status: RunState
    revision: int = Field(ge=0)
    stage: str | None = None
    interrupt: Interrupt | None = None
    error: Error | None = None


class RunSummary(Contract):
    """실행 목록의 한 줄 (`GET /runs`). 소유자 본인의 실행만 돌려준다 (ADR-0011)."""

    run_id: UUID
    status: RunState
    revision: int = Field(ge=0)
    created_at: datetime


class ExcludedBlock(Contract):
    """추출 확인에서 뺄 원문 블록. 사유는 `review` 블록이면 필수, `fail` 블록이면 선택이다.

    블록 판정과 맞지 않으면 resume API가 422 `INVALID_RESPONSE`로 막는다: 없는 블록, `pass` 블록,
    `review` 블록의 빈 사유(공백만 있는 사유 포함), 같은 블록 두 번 (06 문서, #120).
    `fail` 블록의 빈 사유(`""`)는 사유 없음으로 블록에 남긴다 (`SourceRequirement.excluded_reason`).
    """

    block_id: NonEmptyText
    reason: str | None = None


class ExtractionResponse(Contract):
    """추출 확인 응답. 문장을 고치지 않고 확인 또는 제외만 한다 (ADR-0015, #95).

    제외 목록에 없는 `review` 블록은 확인으로 보고, 제외하지 않은 `fail` 블록이 있으면 422다.
    실행기가 결정을 `SourceRequirement.user_decision`·`excluded_reason`에 남기고, 분석할 블록이
    0건이면 `EXTRACTION_FAILED`로 끝낸다.
    """

    kind: Literal["extraction"]
    confirmed: bool  # false는 중단(`cancelled`). 이때 `excluded_blocks`는 비워야 한다(어기면 422)
    excluded_blocks: tuple[ExcludedBlock, ...] = ()


class RequirementAnswer(Contract):
    """분석 확인(HITL 1)에서 요구사항 하나에 대한 답 (06 문서 resume).

    - keep: 그대로 둔다. `texts`는 비운다
    - edit: `texts` 1개로 문장(`text`)을 바꾼다. A01이 낸 `draft_text`는 남는다
    - split: `texts` 2개 이상으로 나눈다. 첫 조각은 원래 ID, 나머지는 서버가 새 ID를 붙이고
      원문 연결·분류는 원래 요구사항과 같다
    """

    req_id: NonEmptyText
    action: Literal["keep", "edit", "split"]
    texts: tuple[str, ...]


class RequirementsResponse(Contract):
    """분석 확인(HITL 1) 응답. 답이 없는 요구사항은 keep으로 본다.

    질문(`QualityIssue.question`)의 답은 edit 문장으로 반영한다. 없는 ID·같은 ID 두 번·문장 수가
    맞지 않는 답은 그래프가 반영하지 않고 실행을 `INTERNAL`로 끝낸다 (#123). resume API의 422 검사는
    아직 없다.
    """

    kind: Literal["requirements"]
    answers: tuple[RequirementAnswer, ...]


class ReviewResponse(Contract):
    """최종 검토(HITL 2) 응답 (06 문서 resume).

    - approve: 현재 revision을 승인하고 내보낸다. 차단 오류(critical)가 남아 있으면 422 (ADR-0010)
    - revise: 수정 요청 문장(`feedback`)으로 A09가 복귀 단계를 정한다. 비었거나 정하지 못하면
      최종 검토를 다시 묻는다
    - hold: `status` 이벤트만 남기고 같은 확인 요청으로 계속 기다린다
    """

    kind: Literal["review"]
    decision: Literal["approve", "revise", "hold"]
    feedback: str


ResumeResponse = Annotated[
    ExtractionResponse | RequirementsResponse | ReviewResponse, Field(discriminator="kind")
]


class ResumeRequest(Contract):
    """사람 확인에 대한 답 (`POST /runs/{id}/resume`).

    `interrupt_id`·`expected_revision`은 지금 기다리는 요청과 같아야 한다. 오래되었거나 이미 답한
    요청이면 409 `INTERRUPT_STALE`, revision이 다르면 409 `RUN_REVISION_CONFLICT`,
    `response.kind`가 확인 종류와 다르면 422 `INVALID_RESPONSE`다.
    """

    interrupt_id: NonEmptyText
    expected_revision: int = Field(ge=0)
    response: ResumeResponse


class RunView(Contract):
    """화면용 읽기 모델. 항목의 세부 구조는 섹션별로 설계 모델(design.py)을 직렬화해 쓴다."""

    run_id: UUID
    revision: int = Field(ge=0)
    section: Literal["extraction", "requirements", "design", "review"]
    items: tuple[dict[str, Any], ...]
    artifacts: tuple[dict[str, Any], ...] = ()


class SseEventType(StrEnum):
    """SSE 이벤트 종류 (06 문서 SSE).

    - status: 상태 변화. 분석 확인(HITL 1)을 건너뛰면 `designing` 이벤트 메시지로 알린다 (UI-04)
    - interrupt: 사람 확인 대기. payload는 `interrupt_id`·`kind`, 최종 검토면
      `failed_branches`·`hitl_reason`도
    - artifact: 산출물 생성 (생성 노드 #12~#15 연결 뒤)
    - error: 실행 실패. payload는 `code`·`retryable`
    - completed·cancelled: 실행 종료
    """

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
