"""입력 원문과 요구사항 (A01 출력, 05 문서)."""

from pydantic import Field

from specton.contracts.base import (
    Contract,
    ExtractionStatus,
    NfrCategory,
    NonEmptyText,
    ReqId,
    RequirementType,
    SourceRef,
)


class RawRequirement(Contract):
    """추출된 원문 한 건. 코드가 만들고 LLM은 만들지 않는다."""

    document_id: NonEmptyText
    block_id: NonEmptyText
    source_id: str | None = None  # 고객 문서의 원문 ID (예: SFR-001). 그대로 보존
    source_ref: SourceRef
    text: NonEmptyText
    extraction_status: ExtractionStatus = ExtractionStatus.OK


class QualityIssue(Contract):
    """A01이 지적하는 품질 경고(모호 표현 등)와 사용자에게 할 확인 질문."""

    kind: NonEmptyText
    message: NonEmptyText
    question: str | None = None


class RequirementDraft(Contract):
    """A01 LLM 출력. ID와 버전은 코드가 붙인다."""

    source_block_ids: list[NonEmptyText] = Field(min_length=1)
    text: NonEmptyText
    type: RequirementType
    nfr_category: NfrCategory | None = None
    parent_hint: str | None = None  # 분할 전 요구의 단서. 실제 parent_id는 코드가 연결한다
    quality_issues: list[QualityIssue] = Field(default_factory=list)


class Requirement(Contract):
    """저장 모델. `id`·`source_id`·`source_ref`·`parent_id`·`analysis_version`은 코드가 채운다."""

    id: ReqId
    source_id: str | None = None
    source_ref: SourceRef
    parent_id: ReqId | None = None
    text: NonEmptyText
    original_text: NonEmptyText  # 사용자 수정 전 분석 결과. 수정본과 구분한다
    type: RequirementType
    nfr_category: NfrCategory | None = None
    quality_issues: list[QualityIssue] = Field(default_factory=list)
    analysis_version: int = Field(ge=1)
