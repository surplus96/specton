"""명시적 FK 재사용의 키·타입·NULL 검증. 의미는 관계 선언으로 받고 이름으로 추론하지 않는다."""

from collections.abc import Iterable

from specton.contracts import Column, Relationship, Table

SQL_TYPE_FIELDS = ("data_type", "length", "precision", "scale", "time_precision")


def fk_nullability_matches(
    nullabilities: Iterable[bool], *, optional: bool, identifying: bool
) -> bool:
    """MATCH SIMPLE: 선택 FK는 한 칸 이상 NULL 가능, 필수·식별 FK는 모두 NOT NULL."""
    values = tuple(nullabilities)
    return bool(values) and (any(values) if optional and not identifying else not any(values))


def same_key_type(parent: Column, child: Column) -> bool:
    """SQL 타입은 정확히 같고, 도메인이 양쪽에 명시되어 있으면 같은 도메인이어야 한다."""
    return all(getattr(parent, f) == getattr(child, f) for f in SQL_TYPE_FIELDS) and (
        parent.domain is None or child.domain is None or parent.domain == child.domain
    )


def binding_columns(rel: Relationship, parent: Table, child: Table) -> dict[str, Column]:
    """부모 PK 컬럼 ID → 자식 기존 컬럼. 유효하지 않은 선언은 생성 전 거절한다."""
    parent_keys = {
        c.attribute_id: c
        for c in parent.columns
        if c.id in parent.primary_key and c.attribute_id is not None
    }
    child_attributes = {c.attribute_id: c for c in child.columns if c.attribute_id is not None}
    result: dict[str, Column] = {}
    for binding in rel.fk_bindings or ():
        key = parent_keys.get(binding.parent_attribute_id)
        column = child_attributes.get(binding.child_attribute_id)
        if key is None or column is None:
            raise ValueError(
                "FK 재사용은 부모의 직접 PK 속성과 자식의 기존 업무 속성을 가리켜야 함"
            )
        if not same_key_type(key, column):
            raise ValueError(f"FK 재사용 타입·도메인 불일치: {key.name} → {column.name}")
        result[key.id] = column
    if result and not fk_nullability_matches(
        (
            result[key].nullable if key in result else rel.optional and not rel.identifying
            for key in parent.primary_key
        ),
        optional=rel.optional,
        identifying=rel.identifying,
    ):
        raise ValueError(
            "FK 재사용 NULL 조건 불일치: 필수 FK는 모두 NOT NULL, 선택 FK는 NULL 가능 칸이 필요"
        )
    return result


def declared_reuse(rel: Relationship, parent: Column, child: Column) -> bool:
    """출처·타입이 명시적 쌍과 맞는지 확인한다. NULL은 FK 묶음 전체로 검사한다."""
    return same_key_type(parent, child) and any(
        b.parent_attribute_id == parent.attribute_id and b.child_attribute_id == child.attribute_id
        for b in rel.fk_bindings or ()
    )
