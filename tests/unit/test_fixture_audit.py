"""자료 감사를 승인이나 의미 채점으로 오인하지 않도록 경계를 검증한다."""

import json
from pathlib import Path

import pytest
import yaml

from specton.review.eval_fixtures import FixtureError, load_fixture_set
from specton.review.fixture_audit import audit, main, structure_hash

SAMPLE = Path(__file__).parent / "data" / "review_eval_sample.yaml"


def test_audit_preserves_source_and_does_not_approve(tmp_path: Path) -> None:
    original = SAMPLE.read_bytes()
    report = audit(SAMPLE)
    assert SAMPLE.read_bytes() == original
    assert report["case_counts"] == {"normal": 1, "defect": 2, "alt_normal": 1}
    assert report["defect_counts"] == {"cardinality": 1, "direction": 1}
    assert report["cases"][1]["expected"] == [
        {"target": "REL-01", "target_kind": "relationship", "defect": "cardinality"}
    ]
    assert report["semantic_validation"] == "not_performed"
    assert report["approval"] == "not_granted"


def test_description_variants_share_structure_but_relationship_changes_do_not() -> None:
    fixtures = load_fixture_set(SAMPLE)
    normal = fixtures.cases[0]
    variant = normal.evolve(
        entities=tuple(e.evolve(description="다른 설명") for e in normal.entities)
    )
    assert structure_hash(normal) == structure_hash(variant)
    assert structure_hash(normal) != structure_hash(fixtures.cases[1])
    assert structure_hash(normal) != structure_hash(fixtures.cases[2])


def test_audit_groups_only_normals_and_lists_metadata_hints(tmp_path: Path) -> None:
    data = yaml.safe_load(SAMPLE.read_text())
    variant = dict(data["cases"][0], case_id="EXTRA-A", case="alt_normal")
    variant["source_id"] = "label-cardinality"
    data["cases"].append(variant)
    path = tmp_path / "input.yaml"
    path.write_text(yaml.safe_dump(data))
    report = audit(path)
    assert report["same_normal_structure_groups"] == [["SAMPLE-01-N", "EXTRA-A"]]
    assert report["normal_structure_count"] == 2
    assert report["source_ids_containing_defect_labels"] == ["EXTRA-A"]


def test_order_changes_do_not_inflate_structure_count() -> None:
    case = load_fixture_set(SAMPLE).cases[0]
    assert structure_hash(case) == structure_hash(
        case.evolve(entities=tuple(reversed(case.entities)))
    )


@pytest.mark.parametrize("existing", ["output", "input"])
def test_cli_never_overwrites_input_or_existing_reports(tmp_path: Path, existing: str) -> None:
    path = tmp_path / "fixtures.yaml"
    path.write_bytes(SAMPLE.read_bytes())
    output = path if existing == "input" else tmp_path / "report.json"
    if existing == "output":
        output.write_text("preserve")
    before = output.read_bytes()
    with pytest.raises(SystemExit) as error:
        main([str(path), "--out", str(output)])
    assert error.value.code == 2
    assert output.read_bytes() == before


def test_invalid_fixture_is_not_reported_as_valid(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("cases: []")
    with pytest.raises(FixtureError):
        audit(path)


def test_cli_emits_a_private_report_without_api_calls(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    assert main([str(SAMPLE), "--out", str(output)]) == 0
    assert json.loads(output.read_text())["audit_version"] == "fixture-audit-v1"
