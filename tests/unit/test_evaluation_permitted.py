"""합성 정답으로 OR 경고·원문 경고·허용 지적의 분모를 검증한다."""

from typing import Any

import pytest

from specton.evaluation.metrics import matching_counts, splits, warning_counts, warnings
from specton.evaluation.models import Classification, Detection, WarningPolicy
from specton.evaluation.report import build_report, combined_classification
from tests.unit.test_evaluation_scoring import example


@pytest.mark.parametrize(
    "actual", [[], ["missing_value"], ["ambiguous"], ["missing_value", "ambiguous"]]
)
def test_warning_alternatives_count_as_one_requirement(actual: list[str]) -> None:
    policy = WarningPolicy(required_warning_groups=(frozenset({"missing_value", "ambiguous"}),))
    score, permitted = warning_counts(policy, frozenset(actual))
    assert (score.tp, score.fp, score.fn, permitted) == (bool(actual), 0, not actual, 0)


def test_source_warning_is_not_duplicated_or_bound_to_arbitrary_child() -> None:
    data = {
        "gold": [
            {"id": "G1", "source_id": "S", "label": "FR"},
            {"id": "G2", "source_id": "S", "label": "FR"},
        ],
        "predicted": [
            {"id": "P1", "source_id": "S", "label": "FR", "warnings": ["missing_target"]},
            {
                "id": "P2",
                "source_id": "S",
                "label": "FR",
                "warnings": ["missing_target", "ambiguous", "not_a_requirement"],
            },
        ],
        "source_warnings": {
            "S": {
                "required_warnings": ["missing_target"],
                "required_warning_groups": [["missing_value", "ambiguous"]],
                "allowed_warnings": ["not_a_requirement"],
            }
        },
    }
    score = warnings(Classification.model_validate(data))
    assert (score["tp"], score["fp"], score["fn"], score["permitted"]) == (2, 0, 0, 1)
    data["predicted"] = []
    assert warnings(Classification.model_validate(data))["fn"] == 2


@pytest.mark.parametrize(
    "policy",
    [
        {"required_warning_groups": [["single"]]},
        {"required_warnings": ["a"], "required_warning_groups": [["a", "b"]]},
        {"allowed_warnings": ["b"], "required_warning_groups": [["a", "b"]]},
        {"required_warning_groups": [["a", "b"], ["b", "c"]]},
    ],
)
def test_ambiguous_warning_denominators_are_rejected(policy: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        WarningPolicy.model_validate(policy)


def test_source_policy_cannot_hide_item_warning_or_reference_missing_source() -> None:
    with pytest.raises(ValueError, match="이중"):
        Classification.model_validate(
            {
                "gold": [
                    {"id": "G", "source_id": "S", "label": "FR", "required_warnings": ["ambiguous"]}
                ],
                "source_warnings": {"S": {}},
            }
        )
    with pytest.raises(ValueError, match="원문"):
        Classification(source_warnings={"missing": WarningPolicy()})


def permitted_detection() -> dict[str, Any]:
    return {
        "gold": ["must-find", "missed"],
        "predicted": ["hit", "allowed-hit", "false-alarm"],
        "matches": [{"gold": ["must-find"], "predicted": ["hit"]}],
        "permitted": {
            "gold": ["optional-issue", "optional-not-reported"],
            "predicted": ["allowed-hit"],
            "matches": [{"gold": ["optional-issue"], "predicted": ["allowed-hit"]}],
        },
    }


def test_permitted_defects_are_neither_tp_fn_nor_fp() -> None:
    counts = matching_counts(Detection.model_validate(permitted_detection()))
    assert (counts.tp, counts.fp, counts.fn) == (1, 1, 1)


@pytest.mark.parametrize("problem", ["not_output", "overlap", "no_match", "same_gold"])
def test_permitted_exclusions_require_disjoint_approved_matches(problem: str) -> None:
    data = permitted_detection()
    if problem == "not_output":
        data["predicted"].remove("allowed-hit")
    elif problem == "overlap":
        data["matches"][0]["predicted"] = ["allowed-hit"]
    elif problem == "no_match":
        data["permitted"]["matches"] = []
    else:
        data["gold"].append("optional-issue")
    with pytest.raises(ValueError):
        Detection.model_validate(data)


def test_report_keeps_permitted_separate_and_namespaces_source_policies() -> None:
    from specton.evaluation.models import Evaluation

    payload = example()
    doc = payload["documents"][0]
    doc["classification"] = {
        "gold": [{"id": "G", "source_id": "S", "label": "FR"}],
        "source_warnings": {"S": {"required_warnings": ["missing_value"]}},
    }
    doc["detections"]["filtered"] = {
        "normal": True,
        "predicted": ["allowed-hit", "false-alarm"],
        "permitted": {
            "gold": ["optional"],
            "predicted": ["allowed-hit"],
            "matches": [{"gold": ["optional"], "predicted": ["allowed-hit"]}],
        },
    }
    evaluation = Evaluation.model_validate(payload)
    merged = combined_classification([evaluation.documents[0], evaluation.documents[0]])
    assert len(merged.source_warnings) == 2
    assert warnings(merged)["fn"] == 2
    report = build_report(evaluation)["conditions"]["with_pack"]["detections"]["filtered"]
    assert report["permitted_predictions"] == 1
    assert report["normal_false_positives"] == 1
    assert report["micro"]["fp"] == 1


def test_approved_split_alternatives_do_not_require_primary_count() -> None:
    items = Classification.model_validate(
        {
            "gold": [{"id": "G", "source_id": "S", "label": "FR"}],
            "predicted": [
                {"id": "P1", "source_id": "S", "label": "FR"},
                {"id": "P2", "source_id": "S", "label": "FR"},
            ],
            "allowed_split_counts": {"S": [1, 2]},
        }
    )
    assert splits(items)["accuracy"] == 1
    assert splits(items)["counts"]["S"] == {"expected": 1, "actual": 2, "allowed": [1, 2]}


@pytest.mark.parametrize("counts", [{"missing": [1]}, {"S": []}, {"S": [2]}, {"S": [0, 1]}])
def test_split_policy_requires_real_source_and_primary_count(counts: dict[str, list[int]]) -> None:
    with pytest.raises(ValueError):
        Classification.model_validate(
            {
                "gold": [{"id": "G", "source_id": "S", "label": "FR"}],
                "allowed_split_counts": counts,
            }
        )
