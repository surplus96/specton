"""A08 평가 연결. 평가 자료 대신 새 합성 설계와 실제 승인 팩을 쓴다."""

import json
from pathlib import Path
from typing import Any

import pytest

from specton.config import Settings
from specton.contracts import Finding
from specton.llm.stub import reply, stub_client
from specton.nodes.common import unwrap_data
from specton.review import eval_normalization
from specton.review.eval_fixtures import (
    CaseResult,
    FixtureError,
    FixtureSet,
    build_report,
    run_cases,
)
from specton.review.perspective import PERSPECTIVES_DIR, load_perspective

A08 = load_perspective(PERSPECTIVES_DIR / "A08.yaml")
SETTINGS = Settings(_env_file=None)


def fixture() -> dict[str, Any]:
    return {
        "reviewer_id": "A08",
        "set": "synthetic-a08-v1",
        "pack": "inventory",
        "cases": [
            {
                "case_id": "synthetic-1",
                "source_id": "synthetic",
                "case": "defect",
                "requirements": [{"id": "REQ-01", "type": "FR", "text": "창고 이름을 관리한다."}],
                "entities": [
                    {
                        "id": "ENT-01",
                        "name": "창고",
                        "req_ids": ["REQ-01"],
                        "attributes": [
                            {
                                "id": "ATTR-01",
                                "name": "창고코드",
                                "data_type": "varchar",
                                "length": 10,
                                "is_key": True,
                                "nullable": False,
                                "req_ids": ["REQ-01"],
                            },
                            {
                                "id": "ATTR-02",
                                "name": "창고명",
                                "data_type": "varchar",
                                "length": 200,
                                "req_ids": ["REQ-01"],
                            },
                        ],
                    }
                ],
                "expected": [{"target": "ATTR-02", "defect": "duplicate_fact"}],
            }
        ],
    }


def test_a08_receives_real_normalized_columns_and_preserves_original_targets() -> None:
    fixtures = FixtureSet.model_validate(fixture())
    response = {
        "findings": [
            {
                "kind": "duplicate_fact",
                "severity": "major",
                "targets": [{"kind": "attribute", "id": "ATTR-02"}],
                "evidence": [{"req_id": "REQ-01", "quote": "창고 이름"}],
                "suggestion": "같은 사실의 저장 위치를 확인한다",
                "target_stage": "data_model",
            }
        ]
    }
    client, transport = stub_client(reply(json.dumps(response)))
    [result] = run_cases(client, A08, fixtures, SETTINGS)
    data = json.loads(unwrap_data(transport.sent[0].messages[-1].content))
    assert set(data) == {"requirements", "entities", "relationships", "normalized"}
    assert data["entities"][0]["attributes"][1]["id"] == "ATTR-02"
    assert data["normalized"]["tables"][0]["columns"][1]["attribute_id"] in {"ATTR-01", "ATTR-02"}
    assert result.ok and result.found == ("ATTR-02",)
    assert result.provenance["common_version"] == "0.1.6"
    assert result.provenance["pack_version"] == "0.1.21"
    assert len(result.provenance["policy_digest"]) == 64
    report = build_report(fixtures, A08, [result])
    assert report["cases"][0]["provenance"] == result.provenance


def test_invalid_later_case_is_a_fixture_error_before_any_llm_call() -> None:
    data = fixture()
    second = json.loads(json.dumps(data["cases"][0]))
    second["case_id"] = "invalid-second"
    second["entities"][0]["attributes"][0]["is_key"] = False
    data["cases"].append(second)
    client, transport = stub_client()
    with pytest.raises(FixtureError, match=r"invalid-second.*no_primary_key"):
        run_cases(client, A08, FixtureSet.model_validate(data), SETTINGS)
    assert transport.sent == ()


def test_missing_explicit_attributes_does_not_invent_an_a08_key() -> None:
    data = fixture()
    data["cases"][0]["entities"][0].pop("attributes")
    data["cases"][0]["expected"] = [{"target": "ENT-01", "defect": "derived_value"}]
    client, transport = stub_client()
    with pytest.raises(FixtureError, match="attributes"):
        run_cases(client, A08, FixtureSet.model_validate(data), SETTINGS)
    assert transport.sent == ()


def test_custom_pack_root_never_falls_back_to_default(tmp_path: Path) -> None:
    client, transport = stub_client()
    with pytest.raises(FixtureError, match="평가 자료 정리 오류"):
        run_cases(
            client,
            A08,
            FixtureSet.model_validate(fixture()),
            Settings(_env_file=None, pack_root=tmp_path),
        )
    assert transport.sent == ()


def test_attribute_references_and_duplicate_target_ids_are_validated() -> None:
    data = fixture()
    data["cases"][0]["entities"][0]["attributes"][1]["req_ids"] = ["REQ-99"]
    with pytest.raises(ValueError, match="REQ-99"):
        FixtureSet.model_validate(data)
    data = fixture()
    data["cases"][0]["entities"][0]["attributes"][1]["id"] = "ENT-01"
    with pytest.raises(ValueError, match="중복"):
        FixtureSet.model_validate(data)


def test_pack_content_must_match_the_approved_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eval_normalization, "pack_content_hash", lambda folder: "changed")
    client, transport = stub_client()
    with pytest.raises(FixtureError, match=r"pack\.lock"):
        run_cases(client, A08, FixtureSet.model_validate(fixture()), SETTINGS)
    assert transport.sent == ()


def test_wrong_target_kind_with_a_correct_id_is_not_a_detected_defect() -> None:
    case = FixtureSet.model_validate(fixture()).cases[0]
    finding = Finding.model_validate(
        {
            "id": "F1",
            "source": "llm",
            "reviewer_id": "A08",
            "kind": "duplicate_fact",
            "severity": "major",
            "targets": [{"kind": "entity", "id": "ATTR-02"}],
            "evidence": [{"req_id": "REQ-01", "quote": "창고"}],
            "suggestion": "저장 위치 확인",
            "target_stage": "data_model",
            "fingerprint": "synthetic",
            "iteration": 0,
        }
    )
    result = CaseResult(case, True, None, (finding,), ())
    assert result.found == () and result.missed == ("ATTR-02",)
    assert not result.matches(finding)


def test_batch_budget_exhaustion_does_not_start_another_call() -> None:
    data = fixture()
    second = json.loads(json.dumps(data["cases"][0]))
    second["case_id"] = "second-case"
    data["cases"].append(second)
    client, transport = stub_client(reply('{"findings": []}', input_tokens=10, output_tokens=10))
    results = run_cases(
        client,
        A08,
        FixtureSet.model_validate(data),
        Settings(_env_file=None, max_tokens_per_run=20),
    )
    assert len(transport.sent) == 1
    assert results[0].ok
    assert results[1].error_code == "BUDGET_EXCEEDED" and not results[1].ok
    assert results[1].calls == ()
