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
    UserDecision,
)


def _check_nfr_category(type_: RequirementType, category: NfrCategory | None) -> None:
    """NFR은 분류가 있어야 하고 FR은 분류를 두지 않는다 (05 문서)."""
    if type_ is RequirementType.NFR and category is None:
        raise ValueError("NFR 요구사항에는 nfr_category가 필요합니다 (애매하면 other)")
    if type_ is RequirementType.FR and category is not None:
        raise ValueError("FR 요구사항에는 nfr_category를 두지 않습니다")


class SourceRequirement(Contract):
    """추출된 원문 한 건. 코드가 만들고 LLM은 만들지 않는다.

    `source_` 칸은 원문에서 온 값이다(코드가 복사하고 해석하지 않음). 앞뒤 공백까지 보존하는
    칸은 `source_text`뿐이고 나머지 `source_` 칸은 앞뒤 공백을 지운다. 추출 확인(UI-02)에서는
    문장을 고치지 않고 확인 또는 제외만 하며, 그 결정을 `user_decision`에 둔다
    (ADR-0015, #95). 노드는 `analysable`인 블록만 분석한다.
    """

    document_id: NonEmptyText
    block_id: NonEmptyText
    source_id: str | None = None  # 고객 문서의 원문 ID (예: SFR-001). 그대로 보존
    source_ref: SourceRef
    # 요구사항명·상세 내용 칸이 모두 빈 행(범례·각주 줄 등)은 None이다. 이때 판정은 `review`
    source_text: SourceText | None
    source_acceptance_level: str | None = None  # 응락수준 원문 (예: 필수·핵심). 해석하지 않는다
    source_related_requirements: str | None = None  # 「관련 요구사항」 칸 원문
    source_extra: dict[str, str] = Field(default_factory=dict)  # 그 밖의 원문 칸 (칸 이름 → 값)
    extraction_status: ExtractionStatus  # 기본값을 두지 않는다. 판정 없이 `pass`가 되지 않게
    # 판정 이유: 화면·RTM에 보여 주는 문구. `review`·`fail`은 필수. 자세한 오류는 로그에만
    notice: str | None = None
    user_decision: UserDecision | None = None  # 결정 전이거나 확인할 필요가 없으면 None
    excluded_reason: NonEmptyText | None = None  # 제외 사유. `review`는 필수, `fail`은 선택

    @model_validator(mode="after")
    def _check_decision(self) -> Self:
        """판정과 사용자 결정이 맞는지 본다 (ADR-0015 결정 5)."""
        status, decision = self.extraction_status, self.user_decision
        if self.source_text is None and status is not ExtractionStatus.REVIEW:
            raise ValueError("원문 문장이 없는 블록은 review여야 합니다")
        if status is not ExtractionStatus.PASS and not self.notice:  # 화면에 확인 이유를 보여 준다
            raise ValueError(f"{status} 블록에는 판정 이유(notice)가 필요합니다")
        if status is ExtractionStatus.PASS and decision is not None:
            raise ValueError("pass 블록에는 사용자 결정을 두지 않습니다")
        if status is ExtractionStatus.FAIL and decision is UserDecision.CONFIRMED:
            raise ValueError("fail 블록은 확인으로 넘기지 못하고 제외해야 합니다")
        if decision is not UserDecision.EXCLUDED and self.excluded_reason is not None:
            raise ValueError("제외하지 않은 블록에는 제외 사유를 두지 않습니다")
        if (
            decision is UserDecision.EXCLUDED
            and status is ExtractionStatus.REVIEW
            and self.excluded_reason is None
        ):
            raise ValueError("review 블록을 제외하려면 사유가 필요합니다")
        return self

    @property
    def analysable(self) -> bool:
        """분석(A01)에 넣을 블록인지. 제외했거나 원문 문장이 없거나 `fail`이면 넣지 않는다.

        `fail` 블록은 제외해야만 진행하므로(ADR-0015 결정 5) 결정 전이어도 분석하지 않는다.
        """
        return (
            self.source_text is not None
            and self.extraction_status is not ExtractionStatus.FAIL
            and self.user_decision is not UserDecision.EXCLUDED
        )


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
    text: NonEmptyText  # 최종 문장 (사용자 확인 후)
    draft_text: NonEmptyText  # A01(LLM)이 낸 문장. 사용자 수정본(text)과 구분한다
    source_text: SourceText | None = None  # 원문 문장 복사 (코드)
    source_acceptance_level: str | None = None  # 응락수준 원문. 분할하면 부모 값을 그대로 쓴다
    type: RequirementType
    nfr_category: NfrCategory | None = None
    quality_issues: tuple[QualityIssue, ...] = ()
    analysis_version: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_category(self) -> Self:
        _check_nfr_category(self.type, self.nfr_category)
        return self
