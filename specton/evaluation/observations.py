"""저장된 DesignState에서 채점 대상만 꺼낸다. 원문·정답·매칭을 생성하지 않는다."""

from collections.abc import Mapping
from typing import Any

from specton.contracts import DesignState
from specton.evaluation.models import Prediction


def requirements(
    state: DesignState, *, source_ids: Mapping[str, str] | None = None
) -> tuple[Prediction, ...]:
    """A01 확인 전 체크포인트를 사용한다. 원문 ID 대응이 있으면 모두 명시해야 한다."""
    predictions = []
    for item in state.requirements:
        if item.source_id is None:
            raise ValueError(f"{item.id}: 원문 ID가 없습니다")
        if source_ids is not None and item.source_id not in source_ids:
            raise ValueError(f"{item.id}: 원문 ID 대응이 없습니다")
        predictions.append(
            Prediction(
                id=item.id,
                source_id=source_ids[item.source_id] if source_ids is not None else item.source_id,
                label=item.type.value,
                warnings=frozenset(issue.kind for issue in item.quality_issues),
            )
        )
    return tuple(predictions)


def objects(state: DesignState) -> dict[str, Any]:
    """기능·모델의 관측 ID. 승인된 매칭은 호출자가 별도로 제공한다."""
    return {
        "functions": [i.id for i in state.functions],
        "entities": [i.id for i in state.entities],
        "attributes": [a.id for entity in state.entities for a in entity.attributes],
        "relationships": [i.id for i in state.relationships],
    }
