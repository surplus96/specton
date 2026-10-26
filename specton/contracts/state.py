"""실행 상태와 추적 무결성 검사 (03·05 문서, REQ-20·21)."""

from collections.abc import Iterator
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
    findings: tuple[Finding, ...] = ()


class DesignState(Contract):
    """그래프 전체가 공유하는 설계 상태. 병렬 가지는 `branch_results`에 따로 기록한다."""

    run_id: ObjectId
    revision: int = Field(default=0, ge=0)
    iteration: int = Field(default=0, ge=0)
    status: RunState = RunState.QUEUED
    interrupt_id: str | None = None
    versions: VersionInfo = Field(default_factory=VersionInfo)
    requirements: tuple[Requirement, ...] = ()
    functions: tuple[Function, ...] = ()
    entities: tuple[Entity, ...] = ()
    relationships: tuple[Relationship, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    findings: tuple[Finding, ...] = ()
    branch_results: dict[str, BranchResult] = Field(default_factory=dict)
    updated_at: datetime | None = None


ObjectKind = Literal["requirement", "function", "entity", "attribute", "relationship"]
TraceIssueKind = Literal["missing_req_ids", "unknown_req_id", "unknown_entity_ref", "duplicate_id"]


class TraceIssue(Contract):
    """추적 무결성 위반 한 건 (REQ-21)."""

    kind: TraceIssueKind
    object_kind: ObjectKind
    object_id: str
    detail: str


def find_trace_issues(state: DesignState) -> list[TraceIssue]:
    """req_ids가 비었거나 현재 revision에 없는 REQ·엔티티를 가리키는 요소를 모두 찾는다.

    첫 오류에서 멈추지 않고 전부 모은다. 최종 승인 전에 이 목록이 비어 있어야 한다.
    """
    req_ids = frozenset(r.id for r in state.requirements)
    entity_ids = frozenset(e.id for e in state.entities)
    return [
        *_duplicate_issues(state),
        *_requirement_issues(state.requirements, req_ids),
        *_function_issues(state.functions, req_ids, entity_ids),
        *_entity_issues(state.entities, req_ids),
        *_relationship_issues(state.relationships, req_ids, entity_ids),
    ]


def _issue(
    kind: TraceIssueKind, object_kind: ObjectKind, object_id: str, detail: str
) -> TraceIssue:
    return TraceIssue(kind=kind, object_kind=object_kind, object_id=object_id, detail=detail)


def _duplicate_issues(state: DesignState) -> Iterator[TraceIssue]:
    groups: tuple[tuple[ObjectKind, tuple[str, ...]], ...] = (
        ("requirement", tuple(r.id for r in state.requirements)),
        ("function", tuple(f.id for f in state.functions)),
        ("entity", tuple(e.id for e in state.entities)),
        ("relationship", tuple(r.id for r in state.relationships)),
    )
    for object_kind, ids in groups:
        seen: set[str] = set()
        for object_id in ids:
            if object_id in seen:
                yield _issue("duplicate_id", object_kind, object_id, "ID가 중복됩니다")
            seen.add(object_id)


def _req_ref_issues(
    object_kind: ObjectKind, object_id: str, ids: tuple[str, ...], known: frozenset[str]
) -> Iterator[TraceIssue]:
    if not ids:
        yield _issue("missing_req_ids", object_kind, object_id, "req_ids가 비어 있습니다")
    for req_id in ids:
        if req_id not in known:
            detail = f"현재 revision에 없는 {req_id}를 참조합니다"
            yield _issue("unknown_req_id", object_kind, object_id, detail)


def _requirement_issues(
    requirements: tuple[Requirement, ...], req_ids: frozenset[str]
) -> Iterator[TraceIssue]:
    for req in requirements:
        if req.parent_id is not None and req.parent_id not in req_ids:
            detail = f"parent_id가 현재 revision에 없는 {req.parent_id}를 가리킵니다"
            yield _issue("unknown_req_id", "requirement", req.id, detail)


def _function_issues(
    functions: tuple[Function, ...], req_ids: frozenset[str], entity_ids: frozenset[str]
) -> Iterator[TraceIssue]:
    for function in functions:
        yield from _req_ref_issues("function", function.id, function.req_ids, req_ids)
        for op in function.entity_ops:
            if op.entity_id not in entity_ids:
                detail = f"없는 엔티티 {op.entity_id}를 참조합니다"
                yield _issue("unknown_entity_ref", "function", function.id, detail)


def _entity_issues(entities: tuple[Entity, ...], req_ids: frozenset[str]) -> Iterator[TraceIssue]:
    for entity in entities:
        yield from _req_ref_issues("entity", entity.id, entity.req_ids, req_ids)
        for attr in entity.attributes:
            yield from _req_ref_issues("attribute", attr.id, attr.req_ids, req_ids)


def _relationship_issues(
    relationships: tuple[Relationship, ...], req_ids: frozenset[str], entity_ids: frozenset[str]
) -> Iterator[TraceIssue]:
    for rel in relationships:
        yield from _req_ref_issues("relationship", rel.id, rel.req_ids, req_ids)
        for ref in (rel.parent, rel.child):
            if ref not in entity_ids:
                detail = f"없는 엔티티 {ref}를 참조합니다"
                yield _issue("unknown_entity_ref", "relationship", rel.id, detail)
