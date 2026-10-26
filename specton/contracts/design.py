"""설계 모델: 기능·엔티티·속성·관계 (A02~A04 출력과 저장 모델, 05 문서).

`*Draft`는 LLM 출력이다. LLM은 ID를 만들지 않으므로 이름이나 코드가 넘긴 허용 목록의 값으로만
다른 객체를 가리킨다. 저장 모델은 Draft를 상속하거나 대응하며 ID·참조 해석은 코드가 한다.
FK 속성은 관계에서 코드가 파생하므로 LLM 출력 모델에 두지 않는다.
"""

from typing import Self

from pydantic import Field, model_validator

from specton.contracts.base import (
    Cardinality,
    Contract,
    Crud,
    EntityId,
    NonEmptyText,
    ObjectId,
    Priority,
    PrioritySource,
    ReqId,
    SqlType,
)


class _PriorityMixin(Contract):
    priority: Priority | None = None
    priority_source: PrioritySource = PrioritySource.UNSPECIFIED

    @model_validator(mode="after")
    def _check_priority(self) -> Self:
        unspecified = self.priority_source is PrioritySource.UNSPECIFIED
        if self.priority is None and not unspecified:
            raise ValueError("priority가 null이면 priority_source는 unspecified여야 합니다")
        if self.priority is not None and unspecified:
            raise ValueError("priority가 있으면 priority_source는 explicit 또는 inferred입니다")
        return self


class FunctionDraft(_PriorityMixin):
    """A02 LLM 출력. 우선순위만으로 기능을 범위에서 빼지 않는다 (ADR-0006)."""

    name: NonEmptyText
    description: NonEmptyText
    priority_rationale: str | None = None
    req_ids: list[ReqId] = Field(min_length=1)


class EntityOp(Contract):
    """기능이 엔티티에 하는 조작. A03가 채우기 전 Function.entity_ops는 비어 있다."""

    entity_id: EntityId
    operations: list[Crud] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ops(self) -> Self:
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("operations에 중복이 있습니다")
        return self


class Function(FunctionDraft):
    id: ObjectId  # 코드가 부여
    entity_ops: list[EntityOp] = Field(default_factory=list)


class CrudExemption(Contract):
    """CRUD 4종 중 일부를 제공하지 않는 근거 (예: 이력 테이블의 삭제 면제)."""

    operation: Crud
    reason: NonEmptyText


class AttributeDraft(Contract):
    name: NonEmptyText
    description: str | None = None
    data_type: SqlType
    length: int | None = Field(default=None, ge=1)
    precision: int | None = Field(default=None, ge=1)
    scale: int | None = Field(default=None, ge=0)
    is_key: bool = False
    nullable: bool = True
    # 자유 SQL은 허용하지 않는다. 허용 표현(AST·연산 범위)은 규칙 검사(#15)와 함께 정한다.
    check: str | None = None
    req_ids: list[ReqId] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_type_params(self) -> Self:
        length_types = {SqlType.CHAR, SqlType.VARCHAR}
        if self.data_type in length_types and self.length is None:
            raise ValueError(f"{self.data_type.value}에는 length가 필요합니다")
        if self.data_type not in length_types and self.length is not None:
            raise ValueError(f"{self.data_type.value}에는 length를 쓰지 않습니다")
        if self.data_type is not SqlType.NUMERIC and (
            self.precision is not None or self.scale is not None
        ):
            raise ValueError("precision·scale은 numeric에만 씁니다")
        if self.scale is not None and (self.precision is None or self.scale > self.precision):
            raise ValueError("scale은 precision 이하여야 합니다")
        if self.is_key and self.nullable:
            raise ValueError("키 속성은 NOT NULL이어야 합니다")
        return self


class EntityDraft(Contract):
    """A03 LLM 출력의 엔티티."""

    name: NonEmptyText
    description: NonEmptyText
    attributes: list[AttributeDraft] = Field(min_length=1)
    req_ids: list[ReqId] = Field(min_length=1)
    crud_exemptions: list[CrudExemption] = Field(default_factory=list)


class EntityOpDraft(Contract):
    """A03 LLM 출력의 기능별 조작. 기능은 코드가 넘긴 ID, 엔티티는 같은 출력의 이름으로 가리킨다."""

    function_id: ObjectId
    entity_name: NonEmptyText
    operations: list[Crud] = Field(min_length=1)


class EntityDesignDraft(Contract):
    """A03 출력 전체."""

    entities: list[EntityDraft] = Field(min_length=1)
    entity_ops: list[EntityOpDraft] = Field(default_factory=list)


class Attribute(AttributeDraft):
    id: ObjectId  # 코드가 부여. 관계·FK 파생의 안정적 내부 참조 키


class Entity(Contract):
    id: EntityId
    pack: NonEmptyText  # 사용한 도메인 팩 ID
    name: NonEmptyText
    description: NonEmptyText
    attributes: list[Attribute] = Field(min_length=1)
    req_ids: list[ReqId] = Field(min_length=1)
    crud_exemptions: list[CrudExemption] = Field(default_factory=list)


class RelationshipDraft(Contract):
    """A04 LLM 출력. 부모·자식은 엔티티 이름, 근거는 요구사항 인용."""

    parent_name: NonEmptyText
    child_name: NonEmptyText
    cardinality: Cardinality
    optional: bool
    identifying: bool = False
    rationale: NonEmptyText
    req_ids: list[ReqId] = Field(min_length=1)


class Relationship(Contract):
    id: ObjectId
    parent: EntityId
    child: EntityId
    cardinality: Cardinality
    optional: bool
    identifying: bool = False
    rationale: NonEmptyText
    req_ids: list[ReqId] = Field(min_length=1)
    # 참조 키 선택·복합 키 표현은 모델 정리(#12)에서 정한다.
