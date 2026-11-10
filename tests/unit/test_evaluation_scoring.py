"""정답 원본 없이 숫자가 정해진 합성 사례로 오프라인 채점을 검증한다."""

import json
from pathlib import Path
from typing import Any

import pytest

from specton.evaluation.__main__ import main
from specton.evaluation.models import Classification, Evaluation, Matching
from specton.evaluation.report import build_report, combined_classification


def example() -> dict[str, Any]:
    classification = {
        "gold": [
            {
                "id": "G1",
                "source_id": "S1",
                "label": "FR",
                "required_warnings": ["missing_value"],
                "allowed_warnings": ["not_a_requirement"],
            },
            {"id": "G2", "source_id": "S2", "label": "NFR"},
            {"id": "G3", "source_id": "S3", "label": "FR", "required_warnings": ["missing_target"]},
        ],
        "predicted": [
            {
                "id": "P1",
                "source_id": "S1",
                "label": "NFR",
                "warnings": ["missing_value", "not_a_requirement", "unexpected"],
            },
            {"id": "P2", "source_id": "S2", "label": "NFR"},
            {"id": "P3", "source_id": "S4", "label": "FR"},
        ],
        "alignments": [{"gold": "G1", "predicted": "P1"}, {"gold": "G2", "predicted": "P2"}],
    }
    versions = {
        "commit": "synthetic-commit",
        "pack": "inventory",
        "pack_version": "0.1.21",
        "common_version": "0.1.5",
        "policy_digest": "a" * 64,
        "models": {"A01": "stub"},
        "prompts": {"A01": "fixture-v1"},
    }
    documents = []
    for i, status in enumerate(("completed", "failed", "not_run")):
        documents.append(
            {
                "document_id": f"doc-{i}",
                "input_hash": "b" * 64,
                "run_id": f"run-{i}",
                "status": status,
                "versions": versions,
            }
        )
    documents[0].update(
        classification=classification,
        ddl="passed",
        input_tokens=100,
        output_tokens=20,
        wall_time_ms=500,
        retries=1,
        reworks=0,
        objects={
            "functions": {
                "gold": ["F1", "F2"],
                "predicted": ["P-F"],
                "matches": [{"gold": ["F1", "F2"], "predicted": ["P-F"]}],
            }
        },
        detections={
            "rule": {
                "gold": ["D1"],
                "predicted": ["R1", "R2"],
                "matches": [{"gold": ["D1"], "predicted": ["R1"]}],
            }
        },
    )
    documents[1].update(input_tokens=5, output_tokens=0, wall_time_ms=100, ddl="error")
    return {
        "dataset": "synthetic",
        "gold_version": "v1",
        "gold_variant": "canonical",
        "gold_hash": "c" * 64,
        "approval_ref": "synthetic-review-1",
        "gold_status": "approved",
        "matching_status": "approved",
        "planned_document_ids": ["doc-0", "doc-1", "doc-2"],
        "documents": documents,
    }


def test_classification_warnings_splits_failures_and_usage_have_explicit_denominators() -> None:
    report = build_report(Evaluation.model_validate(example()))
    scores = report["conditions"]["with_pack"]
    labels = scores["classification"]["labels"]
    assert (labels["FR"]["tp"], labels["FR"]["fp"], labels["FR"]["fn"]) == (0, 1, 2)
    assert labels["NFR"]["f1"] == pytest.approx(2 / 3)
    assert scores["classification"]["macro_f1"] == pytest.approx(1 / 3)
    assert scores["classification"]["confusion"]["FR"]["missing"] == 1
    assert {k: scores["warnings"][k] for k in ("tp", "fp", "fn", "permitted")} == {
        "tp": 1,
        "fp": 1,
        "fn": 1,
        "permitted": 1,
    }
    assert scores["splits"]["accuracy"] == 0.5
    assert (scores["completed_runs"], len(scores["excluded_from_quality"])) == (1, 2)
    assert scores["ddl"]["success_rate"] == pytest.approx(1 / 3)
    assert scores["usage"]["input_tokens"] == {"reported_runs": 2, "total": 105}
    assert scores["usage"]["cost_usd"]["total"] is None


def test_approved_merge_counts_as_one_equivalence_group_and_channels_stay_separate() -> None:
    scores = build_report(Evaluation.model_validate(example()))["conditions"]["with_pack"]
    functions = scores["objects"]["functions"]["micro"]
    assert (functions["tp"], functions["fp"], functions["fn"], functions["f1"]) == (1, 0, 0, 1)
    assert scores["objects"]["entities"]["reported_documents"] == 0
    assert scores["objects"]["entities"]["micro"]["f1"] is None
    assert scores["detections"]["rule"]["micro"]["precision"] == 0.5
    assert scores["detections"]["llm"]["reported_documents"] == 0


def test_same_requirement_ids_in_different_documents_do_not_collide() -> None:
    batch = Evaluation.model_validate(example())
    first = batch.documents[0]
    items = combined_classification([first, first])
    assert len(items.gold) == 6 and len(items.alignments) == 4


@pytest.mark.parametrize(
    "bad",
    [
        {"gold": ["G"], "predicted": ["P"], "matches": [{"gold": ["missing"], "predicted": ["P"]}]},
        {
            "gold": ["G"],
            "predicted": ["P", "P2"],
            "matches": [{"gold": ["G"], "predicted": ["P"]}, {"gold": ["G"], "predicted": ["P2"]}],
        },
    ],
)
def test_invalid_or_double_counted_match_groups_are_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Matching.model_validate(bad)


def test_alignment_cannot_join_different_source_blocks() -> None:
    data = example()["documents"][0]["classification"]
    data["alignments"][0]["predicted"] = "P3"
    with pytest.raises(ValueError, match="원문"):
        Classification.model_validate(data)


def test_conditions_do_not_mix_and_undefined_scores_stay_null() -> None:
    data = example()
    data["documents"].extend(
        {
            **doc,
            "run_id": f"other-{i}",
            "condition": "without_pack",
            "status": "not_run",
            "classification": {},
            "ddl": "not_generated",
            "input_tokens": None,
            "output_tokens": None,
            "objects": {},
            "detections": {},
        }
        for i, doc in enumerate(list(data["documents"]))
    )
    report = build_report(Evaluation.model_validate(data))
    score = report["conditions"]["without_pack"]
    assert score["classification"]["macro_f1"] is None
    assert score["ddl"]["total"] == 3 and score["completed_runs"] == 0


def test_unapproved_gold_duplicate_runs_and_unfinished_ddl_success_are_rejected() -> None:
    data = example()
    data["gold_status"] = "draft"
    with pytest.raises(ValueError):
        Evaluation.model_validate(data)
    data = example()
    data["documents"][1]["run_id"] = "run-0"
    with pytest.raises(ValueError, match="중복"):
        Evaluation.model_validate(data)
    data = example()
    data["documents"][1]["ddl"] = "passed"
    with pytest.raises(ValueError, match="미완료"):
        Evaluation.model_validate(data)


def test_cli_scores_offline_and_never_overwrites_input_or_existing_report(tmp_path: Path) -> None:
    source, output = tmp_path / "input.json", tmp_path / "output.json"
    text = json.dumps(example())
    source.write_text(text)
    assert main([str(source), "--out", str(output)]) == 0
    saved = json.loads(output.read_text())
    assert saved["gold_hash"] == "c" * 64 and saved["runs"][0]["versions"]["models"] == {
        "A01": "stub"
    }
    assert main([str(source), "--out", str(source)]) == 2
    assert source.read_text() == text
    before = output.read_bytes()
    assert main([str(source), "--out", str(output)]) == 2
    assert output.read_bytes() == before


def test_missing_planned_documents_or_mixed_versions_cannot_inflate_success() -> None:
    data = example()
    data["documents"].pop()
    with pytest.raises(ValueError, match="평가 예정"):
        Evaluation.model_validate(data)
    data = example()
    data["documents"][1]["versions"] = {
        **data["documents"][1]["versions"],
        "common_version": "0.1.4",
    }
    with pytest.raises(ValueError, match="버전"):
        Evaluation.model_validate(data)


def test_duplicate_object_ids_and_false_positive_on_normal_design_are_not_hidden() -> None:
    with pytest.raises(ValueError, match="중복"):
        Matching.model_validate({"gold": ["G", "G"]})
    data = example()
    data["documents"][0]["detections"]["filtered"] = {
        "gold": [],
        "predicted": ["false-alarm"],
        "normal": True,
    }
    score = build_report(Evaluation.model_validate(data))["conditions"]["with_pack"]
    assert score["detections"]["filtered"]["normal_false_positives"] == 1
    assert score["detections"]["filtered"]["micro"]["fp"] == 1
