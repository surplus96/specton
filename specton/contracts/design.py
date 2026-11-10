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
    """우선순위와 그 출처 (ADR-0006).

    근거 없는 값이 섞이지 않도록 `priority`가 null이면 `priority_source`는 `unspecified`,
    값이 있으면 `explicit` 또는 `inferred`만 허용한다.
    """

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
    req_ids: tuple[ReqId, ...] = Field(min_length=1)


class EntityOp(Contract):
    """기능이 엔티티에 하는 조작. A03가 채우기 전 Function.entity_ops는 비어 있다."""

    entity_id: EntityId
    operations: tuple[Crud, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ops(self) -> Self:
        if len(set(self.operations)) != len(self.operations):
            raise ValueError("operations에 중복이 있습니다")
        return self


class Function(FunctionDraft):
    """기능 저장 모델. `id`는 코드가 부여하고 `entity_ops`는 A03이 채우기 전까지 비어 있다."""

    id: ObjectId  # 코드가 부여
    entity_ops: tuple[EntityOp, ...] = ()


class CrudExemption(Contract):
    """CRUD 4종 중 일부를 제공하지 않는 근거 (예: 이력 테이블의 삭제 면제)."""

    operation: Crud
    reason: NonEmptyText


class AttributeDraft(Contract):
    """A03 LLM 출력의 속성. 타입별 길이·정밀도 규칙과 키 속성의 NOT NULL을 검사한다.

    값 범위 제약(`check`)은 두지 않는다 (#48 리뷰, ADR-0009).
    """

    name: NonEmptyText
    description: str | None = None
    data_type: SqlType
    length: int | None = Field(default=None, ge=1)
    precision: int | None = Field(default=None, ge=1)
    scale: int | None = Field(default=None, ge=0)
    is_key: bool = False
    is_unique: bool = False  # 중복 금지 (PK가 아닌 업무 키)
    nullable: bool = True
    # 값 범위 등 제약 표현(check)은 두지 않는다. LLM이 SQL을 만들지 않도록 출력에서 빼고,
    # 허용 범위(AST·연산)는 규칙 검사(#15)에서 정한 뒤 저장 모델에 추가한다.
    req_ids: tuple[ReqId, ...] = Field(min_length=1)

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
    attributes: tuple[AttributeDraft, ...] = Field(min_length=1)
    req_ids: tuple[ReqId, ...] = Field(min_length=1)
    crud_exemptions: tuple[CrudExemption, ...] = ()
    unique_keys: tuple[tuple[NonEmptyText, ...], ...] | None = None

    @model_validator(mode="after")
    def _check_unique_keys(self) -> Self:
        _validate_groups(self.unique_keys, {a.name for a in self.attributes})
        return self


class EntityOpDraft(Contract):
    """A03 LLM 출력의 기능별 조작. 기능은 코드가 넘긴 ID, 엔티티는 같은 출력의 이름으로 가리킨다."""

    function_id: ObjectId
    entity_name: NonEmptyText
    operations: tuple[Crud, ...] = Field(min_length=1)


class EntityDesignDraft(Contract):
    """A03 출력 전체."""

    entities: tuple[EntityDraft, ...] = Field(min_length=1)
    entity_ops: tuple[EntityOpDraft, ...] = ()


class Attribute(AttributeDraft):
    """속성 저장 모델. `id`는 코드가 부여하며 관계·FK 파생에서 속성을 가리키는 내부 참조 키다."""

    id: ObjectId  # 코드가 부여. 관계·FK 파생의 안정적 내부 참조 키


class Entity(Contract):
    """엔티티 저장 모델. `id` 부여와 이름 → ID 해석은 코드가 하고 `pack`에 사용한 팩 ID를 남긴다."""

    id: EntityId
    pack: NonEmptyText  # 사용한 도메인 팩 ID
    name: NonEmptyText
    description: NonEmptyText
    attributes: tuple[Attribute, ...] = Field(min_length=1)
    req_ids: tuple[ReqId, ...] = Field(min_length=1)
    crud_exemptions: tuple[CrudExemption, ...] = ()
    unique_keys: tuple[tuple[ObjectId, ...], ...] | None = None

    @model_validator(mode="after")
    def _check_unique_keys(self) -> Self:
        _validate_groups(self.unique_keys, {a.id for a in self.attributes})
        return self


def _validate_groups(groups: tuple[tuple[str, ...], ...] | None, known: set[str]) -> None:
    seen: set[frozenset[str]] = set()
    for group in groups or ():
        key = frozenset(group)
        if not group or len(key) != len(group) or not key <= known:
            raise ValueError(f"UNIQUE 묶음은 존재하는 서로 다른 속성이어야 합니다: {group}")
        if key in seen:
            raise ValueError(f"같은 UNIQUE 묶음이 중복됩니다: {group}")
        seen.add(key)


class ForeignKeyBindingDraft(Contract):
    """부모 키와 같은 사실을 표현하는 자식의 기존 속성. A04가 의미를 명시한다."""

    parent_attribute_name: NonEmptyText
    child_attribute_name: NonEmptyText


class ForeignKeyBinding(Contract):
    """FK 재사용의 명시적 속성 쌍. 이름·타입만으로 추론하지 않는다."""

    parent_attribute_id: ObjectId
    child_attribute_id: ObjectId


class RelationshipDraft(Contract):
    """A04 LLM 출력. 부모·자식은 엔티티 이름, 근거는 요구사항 인용."""

    parent_name: NonEmptyText
    child_name: NonEmptyText
    cardinality: Cardinality
    optional: bool
    identifying: bool = False
    rationale: NonEmptyText
    req_ids: tuple[ReqId, ...] = Field(min_length=1)
    fk_bindings: tuple[ForeignKeyBindingDraft, ...] | None = None

    @model_validator(mode="after")
    def _check_bindings(self) -> Self:
        _validate_bindings(
            [(b.parent_attribute_name, b.child_attribute_name) for b in self.fk_bindings or ()],
            self.cardinality,
        )
        return self


class Relationship(Contract):
    """관계 저장 모델. `parent`·`child`는 코드가 엔티티 이름을 해석한 ID다.

    FK 속성은 코드가 이 관계에서 파생하며, 참조 키 선택은 모델 정리(#12)에서 정한다.
    """

    id: ObjectId
    parent: EntityId
    child: EntityId
    cardinality: Cardinality
    optional: bool
    identifying: bool = False
    rationale: NonEmptyText
    req_ids: tuple[ReqId, ...] = Field(min_length=1)
    fk_bindings: tuple[ForeignKeyBinding, ...] | None = None
    # 참조 키 선택·복합 키 표현은 모델 정리(#12)에서 정한다.

    @model_validator(mode="after")
    def _check_bindings(self) -> Self:
        _validate_bindings(
            [(b.parent_attribute_id, b.child_attribute_id) for b in self.fk_bindings or ()],
            self.cardinality,
        )
        return self


def _validate_bindings(bindings: list[tuple[str, str]], cardinality: Cardinality) -> None:
    if bindings and cardinality is Cardinality.MANY_TO_MANY:
        raise ValueError("N:M 연결 테이블의 FK 재사용은 지원하지 않습니다")
    if len({p for p, _ in bindings}) != len(bindings) or len({c for _, c in bindings}) != len(
        bindings
    ):
        raise ValueError("FK 재사용의 부모·자식 속성은 각각 한 번만 선언합니다")
