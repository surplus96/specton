"""리뷰어에게 보여 줄 정리 결과 요약 (#12, A08 재확인). **임시 구현, 공통 변경 확인 전 초안.**

정리 결과(`NormalizedModel`)에서 정규화 판단에 쓰는 구조만 남긴다.

- 남김: 테이블·컬럼 ID, 원래 엔티티·속성·관계 출처 ID, PK·UNIQUE 컬럼 ID 목록(순서 그대로),
  FK의 자식·부모 테이블 ID와 순서가 대응하는 자식·부모 컬럼 ID 목록
- 뺌: 물리명·타입·길이·정밀도·도메인·NULL 허용. A08 지시상 타입·길이는 정규화 문제가
  아니고 토큰만 늘린다

테이블·컬럼 ID는 구조를 잇는 데만 쓴다. 지적 대상은 계약대로 원래 엔티티·속성·관계 ID다
(`merge._known_targets`). 값은 정리 결과 순서(ID 순)를 그대로 따라 같은 입력이면 같은 요약이다.

이 모듈은 LLM client를 import하지 않는다.
"""

from typing import Any

from specton.contracts.normalized import Column, NormalizedModel, Table


def normalized_view(model: NormalizedModel) -> dict[str, Any]:
    """정리 결과 요약. 리뷰어 입력의 `normalized` 섹션 값이다."""
    return {
        "tables": [_table(t) for t in model.tables],
        "foreign_keys": [
            {
                "id": fk.id,
                "relationship_id": fk.relationship_id,
                "table_id": fk.table_id,
                "columns": list(fk.columns),
                "parent_table_id": fk.parent_table_id,
                "parent_columns": list(fk.parent_columns),  # columns[i] → parent_columns[i]
            }
            for fk in model.foreign_keys
        ],
    }


def _table(table: Table) -> dict[str, Any]:
    source = (
        {"entity_id": table.entity_id}
        if table.entity_id is not None
        else {"relationship_id": table.relationship_id}
    )
    return {
        "id": table.id,
        "name": table.name,
        **source,
        "columns": [_column(c) for c in table.columns],
        "primary_key": list(table.primary_key),
        "unique_keys": [list(group) for group in table.unique_keys],
    }


def _column(column: Column) -> dict[str, Any]:
    # 출처는 속성 또는 관계 중 정확히 하나다 (계약). FK 칸은 관계에서 온다.
    source = (
        {"attribute_id": column.attribute_id}
        if column.attribute_id is not None
        else {"relationship_id": column.relationship_id}
    )
    return {"id": column.id, "name": column.name, **source}
