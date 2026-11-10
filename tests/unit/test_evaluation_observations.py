"""저장 상태 → 채점 입력 변환에서 원문 ID와 관측 경고를 보존한다."""

from pathlib import Path

import pytest

from specton.evaluation.observations import objects, requirements
from specton.review.eval_fixtures import case_state, load_fixture_set

SAMPLE = Path(__file__).parent / "data" / "review_eval_sample.yaml"


def test_observations_use_source_ids_and_existing_object_ids_only() -> None:
    fixtures = load_fixture_set(SAMPLE)
    state = case_state(fixtures, fixtures.cases[0])
    original = state.requirements[0]
    state = state.evolve(
        requirements=(
            original.evolve(quality_issues=({"kind": "missing_value", "message": "기준 확인"},)),
        )
    )
    [prediction] = requirements(state, source_ids={"SAMPLE-01": "approved-source-1"})
    assert (prediction.id, prediction.source_id, prediction.label) == (
        "REQ-01",
        "approved-source-1",
        "FR",
    )
    assert prediction.warnings == {"missing_value"}
    assert "text" not in prediction.model_dump()
    assert objects(state)["relationships"] == ["REL-01"]
    assert objects(state)["attributes"] == ["ENT-01-KEY", "ENT-02-KEY"]


def test_missing_source_mapping_or_source_id_is_not_guessed() -> None:
    fixtures = load_fixture_set(SAMPLE)
    state = case_state(fixtures, fixtures.cases[0])
    with pytest.raises(ValueError, match="대응"):
        requirements(state, source_ids={})
    state = state.evolve(requirements=(state.requirements[0].evolve(source_id=None),))
    with pytest.raises(ValueError, match="원문 ID"):
        requirements(state)
