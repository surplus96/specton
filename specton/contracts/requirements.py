"""입력 원문과 요구사항 (A01 출력, 05 문서)."""

from typing import Self

from pydantic import Field, model_validator

from specton.contracts.base import (
    Contract,
    ExtractionStatus,
    NfrCategory,
    NonEmptyText,
    ReqId,
    RequirementType,
    SourceRef,
    SourceText,
)


def _check_nfr_category(type_: RequirementType, category: NfrCategory | None) -> None:
    """NFR은 분류가 있어야 하고 FR은 분류를 두지 않는다 (05 문서)."""
    if type_ is RequirementType.NFR and category is None:
        raise ValueError("NFR 요구사항에는 nfr_category가 필요합니다 (애매하면 other)")
    if type_ is RequirementType.FR and category is not None:
        raise ValueError("FR 요구사항에는 nfr_category를 두지 않습니다")


class RawRequirement(Contract):
    """추출된 원문 한 건. 코드가 만들고 LLM은 만들지 않는다."""

    document_id: NonEmptyText
    block_id: NonEmptyText
    source_id: str | None = None  # 고객 문서의 원문 ID (예: SFR-001). 그대로 보존
    source_ref: SourceRef
    text: SourceText
    extraction_status: ExtractionStatus = ExtractionStatus.OK


class QualityIssue(Contract):
    """A01이 지적하는 품질 경고(모호 표현 등)와 사용자에게 할 확인 질문."""

    kind: NonEmptyText
    message: NonEmptyText
    question: str | None = None


class RequirementDraft(Contract):
    """A01 LLM 출력. ID와 버전은 코드가 붙인다."""

    source_block_ids: tuple[NonEmptyText, ...] = Field(min_length=1)
    text: NonEmptyText
    type: RequirementType
    nfr_category: NfrCategory | None = None
    parent_hint: str | None = None  # 분할 전 요구의 단서. 실제 parent_id는 코드가 연결한다
    quality_issues: tuple[QualityIssue, ...] = ()

    @model_validator(mode="after")
    def _check_category(self) -> Self:
        _check_nfr_category(self.type, self.nfr_category)
        return self


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
    quality_issues: tuple[QualityIssue, ...] = ()
    analysis_version: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_category(self) -> Self:
        _check_nfr_category(self.type, self.nfr_category)
        return self
