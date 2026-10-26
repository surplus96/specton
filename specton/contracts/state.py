"""실행 상태와 추적 무결성 검사 (03·05 문서, REQ-20·21)."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from specton.contracts.base import Contract, NonEmptyText, ObjectId
from specton.contracts.design import Entity, Function, Relationship
from specton.contracts.findings import Finding
from specton.contracts.requirements import Requirement


class RunState(StrEnum):
    """run 상태. 값은 `docs/api/openapi.json`의 RunStatus.status와 같다."""

    QUEUED = "queued"
    PARSING = "parsing"
    AWAITING_INPUT = "awaiting_input"
    ANALYSING = "analysing"
    AWAITING_REQUIREMENTS = "awaiting_requirements"
    DESIGNING = "designing"
    GENERATING = "generating"
    REVIEWING = "reviewing"
    AWAITING_REVIEW = "awaiting_review"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class VersionInfo(Contract):
    """결과를 재현하기 위해 기록하는 버전. 모두 코드가 채운다."""

    document_hash: str | None = None
    pack_id: str | None = None
    pack_version: str | None = None
    prompt_versions: dict[str, str] = Field(default_factory=dict)  # 에이전트 ID → 프롬프트 버전
    model_names: dict[str, str] = Field(default_factory=dict)  # 에이전트 ID → 모델


class ArtifactRef(Contract):
    kind: Literal["requirements", "functions", "erd", "ddl", "rtm", "review"]
    format: Literal["md", "pdf", "mmd", "sql", "xlsx", "csv"]
    revision: int = Field(ge=0)
    hash: NonEmptyText
    approved: bool = False


class BranchResult(Contract):
    """병렬 가지(DDL·ERD·RTM, 리뷰어)의 결과. 실패를 빈 결과로 바꾸지 않는다."""

    branch: NonEmptyText
    revision: int = Field(ge=0)
    ok: bool
    error_code: str | None = None
    findings: list[Finding] = Field(default_factory=list)


class DesignState(Contract):
    """그래프 전체가 공유하는 설계 상태. 병렬 가지는 `branch_results`에 따로 기록한다."""

    run_id: ObjectId
    revision: int = Field(default=0, ge=0)
    iteration: int = Field(default=0, ge=0)
    status: RunState = RunState.QUEUED
    interrupt_id: str | None = None
    versions: VersionInfo = Field(default_factory=VersionInfo)
    requirements: list[Requirement] = Field(default_factory=list)
    functions: list[Function] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    branch_results: dict[str, BranchResult] = Field(default_factory=dict)
    updated_at: datetime | None = None


ObjectKind = Literal["requirement", "function", "entity", "attribute", "relationship"]


class TraceIssue(Contract):
    """추적 무결성 위반 한 건 (REQ-21)."""

    kind: Literal["missing_req_ids", "unknown_req_id", "unknown_entity_ref", "duplicate_id"]
    object_kind: ObjectKind
    object_id: str
    detail: str


def find_trace_issues(state: DesignState) -> list[TraceIssue]:
    """req_ids가 비었거나 현재 revision에 없는 REQ를 가리키는 설계 요소를 모두 찾는다.

    첫 오류에서 멈추지 않고 전부 모은다. 최종 승인 전에 이 목록이 비어 있어야 한다.
    """
    issues: list[TraceIssue] = []
    req_ids = {r.id for r in state.requirements}
    entity_ids = {e.id for e in state.entities}

    def check_reqs(object_kind: ObjectKind, object_id: str, ids: list[str]) -> None:
        if not ids:
            issues.append(
                TraceIssue(
                    kind="missing_req_ids",
                    object_kind=object_kind,
                    object_id=object_id,
                    detail="req_ids가 비어 있습니다",
                )
            )
        for req_id in ids:
            if req_id not in req_ids:
                issues.append(
                    TraceIssue(
                        kind="unknown_req_id",
                        object_kind=object_kind,
                        object_id=object_id,
                        detail=f"현재 revision에 없는 {req_id}를 참조합니다",
                    )
                )

    def check_unique(object_kind: ObjectKind, ids: list[str]) -> None:
        seen: set[str] = set()
        for object_id in ids:
            if object_id in seen:
                issues.append(
                    TraceIssue(
                        kind="duplicate_id",
                        object_kind=object_kind,
                        object_id=object_id,
                        detail="ID가 중복됩니다",
                    )
                )
            seen.add(object_id)

    check_unique("requirement", [r.id for r in state.requirements])
    check_unique("function", [f.id for f in state.functions])
    check_unique("entity", [e.id for e in state.entities])
    check_unique("relationship", [r.id for r in state.relationships])

    for function in state.functions:
        check_reqs("function", function.id, list(function.req_ids))
        for op in function.entity_ops:
            if op.entity_id not in entity_ids:
                issues.append(
                    TraceIssue(
                        kind="unknown_entity_ref",
                        object_kind="function",
                        object_id=function.id,
                        detail=f"없는 엔티티 {op.entity_id}를 참조합니다",
                    )
                )
    for entity in state.entities:
        check_reqs("entity", entity.id, list(entity.req_ids))
        for attr in entity.attributes:
            check_reqs("attribute", attr.id, list(attr.req_ids))
    for rel in state.relationships:
        check_reqs("relationship", rel.id, list(rel.req_ids))
        for ref in (rel.parent, rel.child):
            if ref not in entity_ids:
                issues.append(
                    TraceIssue(
                        kind="unknown_entity_ref",
                        object_kind="relationship",
                        object_id=rel.id,
                        detail=f"없는 엔티티 {ref}를 참조합니다",
                    )
                )
    return issues
