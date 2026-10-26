"""검토 지적: LLM 출력(FindingDraft)과 저장 모델(Finding) (04·05 문서)."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from specton.contracts.base import Contract, NonEmptyText, ObjectId, ReqId, SourceRef, TargetStage


class Severity(StrEnum):
    """심각도 제안: 규칙 위반 critical, LLM 지적 major/minor (ADR-0010 미정)."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class FindingSource(StrEnum):
    RULE = "rule"
    LLM = "llm"


class FindingTarget(Contract):
    """지적 대상. 대상 ID가 현재 revision에 실재하는지는 코드가 확인한다."""

    kind: Literal["requirement", "function", "entity", "attribute", "relationship"]
    id: NonEmptyText


class Evidence(Contract):
    """근거 인용. 인용이 실재하는지는 코드가 원문에서 확인한다."""

    req_id: ReqId | None = None
    quote: NonEmptyText
    source_ref: SourceRef | None = None


class FindingDraft(Contract):
    """리뷰어 LLM 출력. `id`·`source`·`fingerprint`·`iteration`은 코드가 붙인다."""

    kind: NonEmptyText
    severity: Severity
    targets: tuple[FindingTarget, ...] = Field(min_length=1)
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    suggestion: NonEmptyText
    target_stage: TargetStage | None = None  # 모르면 null. 코드가 해석하지 못하면 A09가 판단


class Finding(FindingDraft):
    id: ObjectId
    source: FindingSource
    reviewer_id: str | None = None  # source=llm: A05~A08 등 관점
    rule_code: str | None = None  # source=rule: RULE-01~07
    fingerprint: NonEmptyText
    iteration: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_origin(self) -> Self:
        if self.source is FindingSource.RULE:
            if self.rule_code is None or self.reviewer_id is not None:
                raise ValueError("규칙 지적은 rule_code만 가집니다")
        elif self.reviewer_id is None or self.rule_code is not None:
            raise ValueError("LLM 지적은 reviewer_id만 가집니다")
        return self
