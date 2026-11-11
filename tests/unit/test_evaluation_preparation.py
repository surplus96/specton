"""가짜 파일·정답만 사용해 준비와 실제 채점 사이의 경계를 확인한다."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from specton.evaluation.models import Evaluation
from specton.evaluation.preparation import digest, main, prepare, selected_gold, split_counts


@pytest.fixture
def catalog(tmp_path: Path) -> Path:
    source, gold = tmp_path / "input.xlsx", tmp_path / "gold.xlsx"
    source.write_bytes(b"synthetic source")
    gold.write_bytes(b"synthetic gold")
    cells = {
        "기대 분류": "혼합",
        "기대 분할 수": 2,
        "허용 분할 수": "1\u223c2",
        "기대 경고(필수)": "missing_value",
        "허용 경고": None,
        "분할 결과별 정답": "첫째 FR, 둘째 NFR/performance",
        "허용 분할 조합": None,
    }
    payload = {
        "kind": "scoring_preparation",
        "a01_gold_status": "approved",
        "gold_version": "synthetic-v1",
        "approval_ref": "private:approval-v1",
        "model_gold_status": "awaiting_author_confirmation",
        "pack_version": "synthetic",
        "common_version": "synthetic",
        "policy_digest": "a" * 64,
        "documents": [
            {
                "document_id": "doc-1",
                "input_file": str(source),
                "input_sha256": digest(source),
                "gold_file": str(gold),
                "gold_sha256": digest(gold),
                "rows": [
                    {"source_id": "S1", "worksheet": "gold", "row": 2, "approved_cells": cells}
                ],
            }
        ],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def choose(plan: dict[str, Any]) -> dict[str, Any]:
    plan["documents"][0]["rows"][0]["selection"] = {
        "variant": "primary",
        "approval_ref": "private:selection-before-run",
        "items": [
            {"id": "G1", "source_id": "S1", "label": "FR"},
            {"id": "G2", "source_id": "S1", "label": "NFR", "required_warnings": ["missing_value"]},
        ],
        "nfr_categories": {"G2": "performance"},
    }
    return plan


def test_plan_preserves_alternatives_without_selecting(catalog: Path) -> None:
    plan = prepare(catalog)
    row = plan["documents"][0]["rows"][0]
    assert row["candidate_split_counts"] == [1, 2]
    assert row["selection"] is None
    assert "allocate_source_warnings_to_children" in row["review_tasks"]
    assert "review_split_semantics" in row["review_tasks"]
    assert plan["model_gold_status"] == "awaiting_author_confirmation"
    with pytest.raises(ValueError):
        Evaluation.model_validate(plan)
    with pytest.raises(ValueError):
        selected_gold(catalog, plan)


def test_explicit_selection_keeps_warning_on_one_child(catalog: Path) -> None:
    result = selected_gold(catalog, choose(prepare(catalog)))
    truth = result["documents"][0]["gold"]
    assert truth[0]["required_warnings"] == []
    assert truth[1]["required_warnings"] == ["missing_value"]
    assert result["documents"][0]["selections"][0]["nfr_categories"] == {"G2": "performance"}
    assert result["ready_to_score"] is False
    with pytest.raises(ValueError):
        Evaluation.model_validate(result)


@pytest.mark.parametrize("field", ["input_file", "gold_file"])
def test_changed_source_is_rejected(catalog: Path, field: str) -> None:
    original = json.loads(catalog.read_text())
    Path(original["documents"][0][field]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="해시"):
        prepare(catalog)


def test_plan_cannot_change_approved_alternatives(catalog: Path) -> None:
    plan = choose(prepare(catalog))
    plan["documents"][0]["rows"][0]["candidate_split_counts"] = [2, 3]
    with pytest.raises(ValueError, match="원본·행·대안"):
        selected_gold(catalog, plan)


@pytest.mark.parametrize("problem", ["source", "duplicate", "category", "approval", "count"])
def test_invalid_selection_is_rejected(catalog: Path, problem: str) -> None:
    plan = choose(prepare(catalog))
    choice = plan["documents"][0]["rows"][0]["selection"]
    if problem == "source":
        choice["items"][0]["source_id"] = "S2"
    elif problem == "duplicate":
        choice["items"][1]["id"] = "G1"
    elif problem == "category":
        choice["nfr_categories"] = {}
    elif problem == "approval":
        choice["approval_ref"] = " "
    else:
        choice["items"].append({"id": "G3", "source_id": "S1", "label": "FR"})
    with pytest.raises(ValueError):
        selected_gold(catalog, plan)


@pytest.mark.parametrize("raw", ["two", "3\u223c1", "1\u223c1000", "0", "-1"])
def test_unsupported_split_range_requires_review(raw: str) -> None:
    with pytest.raises(ValueError):
        split_counts({"기대 분할 수": 1, "허용 분할 수": raw})


def test_cli_refuses_overwrite_and_exports_explicit_choices(
    catalog: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "plan.json"
    monkeypatch.setattr("sys.argv", ["preparation", str(catalog), "--out", str(output)])
    assert main() == 0
    original = output.read_bytes()
    assert main() == 2
    assert output.read_bytes() == original
    output.write_text(json.dumps(choose(json.loads(original))), encoding="utf-8")
    gold = tmp_path / "selected.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "preparation",
            str(catalog),
            "--selections",
            str(output),
            "--out",
            str(gold),
        ],
    )
    assert main() == 0
    assert json.loads(gold.read_text())["ready_to_score"] is False


def test_unapproved_catalog_is_not_promoted(catalog: Path) -> None:
    payload = json.loads(catalog.read_text())
    payload["a01_gold_status"] = "draft"
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="승인된"):
        prepare(catalog)


@pytest.mark.parametrize("problem", ["empty_documents", "empty_rows", "documents", "sources"])
def test_empty_or_duplicate_catalog_is_rejected(catalog: Path, problem: str) -> None:
    payload = json.loads(catalog.read_text())
    if problem == "empty_documents":
        payload["documents"] = []
    elif problem == "empty_rows":
        payload["documents"][0]["rows"] = []
    elif problem == "documents":
        payload["documents"].append(payload["documents"][0])
    else:
        payload["documents"][0]["rows"].append(payload["documents"][0]["rows"][0])
    catalog.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        prepare(catalog)


def test_selection_can_preserve_source_warning_alternatives(catalog: Path) -> None:
    plan = choose(prepare(catalog))
    selection = plan["documents"][0]["rows"][0]["selection"]
    selection["items"][1].pop("required_warnings")
    selection["source_warnings"] = {
        "required_warning_groups": [["missing_value", "ambiguous"]],
    }
    document = selected_gold(catalog, plan)["documents"][0]
    assert set(document["source_warnings"]["S1"]["required_warning_groups"][0]) == {
        "missing_value",
        "ambiguous",
    }
    assert document["allowed_split_counts"] == {"S1": [1, 2]}


def test_prepared_gold_is_stable_across_python_hash_seeds(catalog: Path, tmp_path: Path) -> None:
    plan = choose(prepare(catalog))
    plan["documents"][0]["rows"][0]["selection"]["items"][1]["allowed_warnings"] = [
        "missing_target",
        "not_a_requirement",
        "ambiguous",
    ]
    selected = tmp_path / "selected.json"
    selected.write_text(json.dumps(plan), encoding="utf-8")
    code = (
        "import json,sys; from pathlib import Path; "
        "from specton.evaluation.preparation import selected_gold; "
        "print(json.dumps(selected_gold(Path(sys.argv[1]), "
        "json.loads(Path(sys.argv[2]).read_text())), sort_keys=True))"
    )
    outputs = [
        subprocess.run(
            [sys.executable, "-c", code, str(catalog), str(selected)],
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for seed in ("1", "2")
    ]
    assert outputs[0] == outputs[1]
