"""검토 관점 평가 고정 설계 (#40, docs/07 「검토 관점 평가」)."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from specton.config import Settings
from specton.contracts import FindingDraft
from specton.llm.stub import refusal, reply, stub_client
from specton.nodes.common import unwrap_data
from specton.review import eval_fixtures
from specton.review.eval_fixtures import (
    FixtureError,
    build_report,
    case_state,
    load_fixture_set,
    main,
    run_cases,
    summarize,
)
from specton.review.perspective import PERSPECTIVES_DIR, Perspective, load_perspective
from specton.review.reviewer import ReviewOutput

SAMPLE = Path(__file__).parent / "data" / "review_eval_sample.yaml"
SETTINGS = Settings(_env_file=None)
A05 = load_perspective(PERSPECTIVES_DIR / "A05.yaml")


def _sample() -> dict[str, Any]:
    return yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "fixtures.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _finding(*target_ids: str, kind: str = "relationship") -> FindingDraft:
    return FindingDraft(
        kind="cardinality_conflict",
        severity="major",
        targets=[{"kind": kind, "id": t} for t in target_ids],
        evidence=[{"req_id": "REQ-01", "quote": "주문 하나에는"}],
        suggestion="요구사항의 수량 표현에 맞게 관계를 고친다",
        target_stage="data_model",
    )


def _answers(*findings_per_case: tuple[FindingDraft, ...]) -> list[Any]:
    return [reply(ReviewOutput(findings=f)) for f in findings_per_case]


class TestLoad:
    def test_sample_file_loads_every_case_kind(self) -> None:
        fixtures = load_fixture_set(SAMPLE)

        assert fixtures.reviewer_id == "A05"
        assert fixtures.set_name == "합성_예시_v1"
        assert [c.case for c in fixtures.cases] == ["normal", "defect", "defect", "alt_normal"]
        assert fixtures.cases[1].expected[0].defect == "cardinality"

    @pytest.mark.parametrize(
        ("index", "expected", "message"),
        [
            (1, [], "defect 사례에는 expected가 하나 이상 필요"),
            (
                0,
                [{"target": "REL-01", "defect": "optional"}],
                "normal 사례에는 expected를 두지 않습니다",
            ),
        ],
    )
    def test_expected_must_match_the_case_kind(
        self, tmp_path: Path, index: int, expected: list[dict[str, str]], message: str
    ) -> None:
        data = _sample()
        data["cases"][index]["expected"] = expected

        with pytest.raises(FixtureError, match=message):
            load_fixture_set(_write(tmp_path, data))

    def test_expected_target_must_be_a_relationship_in_the_case(self, tmp_path: Path) -> None:
        data = _sample()
        data["cases"][1]["expected"] = [{"target": "REL-09", "defect": "cardinality"}]

        with pytest.raises(FixtureError, match="REL-09"):
            load_fixture_set(_write(tmp_path, data))

    def test_relationship_must_point_to_entities_in_the_case(self, tmp_path: Path) -> None:
        data = _sample()
        data["cases"][0]["relationships"][0]["child"] = "ENT-09"

        with pytest.raises(FixtureError, match="ENT-09"):
            load_fixture_set(_write(tmp_path, data))

    def test_relationship_req_ids_must_exist_in_the_case(self, tmp_path: Path) -> None:
        data = _sample()
        data["cases"][0]["relationships"][0]["req_ids"] = ["REQ-02"]

        with pytest.raises(FixtureError, match="REQ-02"):
            load_fixture_set(_write(tmp_path, data))

    def test_duplicate_case_ids_are_rejected(self, tmp_path: Path) -> None:
        data = _sample()
        data["cases"][1]["case_id"] = data["cases"][0]["case_id"]

        with pytest.raises(FixtureError, match="SAMPLE-01-N"):
            load_fixture_set(_write(tmp_path, data))

    def test_unknown_field_is_rejected_with_the_file_path(self, tmp_path: Path) -> None:
        data = _sample()
        data["cases"][0]["note"] = "메모"

        with pytest.raises(FixtureError, match=r"fixtures\.yaml"):
            load_fixture_set(_write(tmp_path, data))


class TestCaseState:
    def test_state_keeps_fixture_semantics_and_fills_the_rest(self) -> None:
        fixtures = load_fixture_set(SAMPLE)

        state = case_state(fixtures, fixtures.cases[1])

        assert state.versions.pack_id == "inventory"
        [req] = state.requirements
        assert (req.id, req.type.value, req.source_id) == ("REQ-01", "FR", "SAMPLE-01")
        assert req.text == req.draft_text == fixtures.cases[1].requirements[0].text
        [rel] = state.relationships
        assert (rel.parent, rel.child, rel.cardinality.value) == ("ENT-01", "ENT-02", "1:1")
        assert (rel.optional, rel.identifying, rel.req_ids) == (False, True, ("REQ-01",))
        assert rel.rationale == "요구사항 REQ-01에 따른 관계"
        order = state.entities[0]
        assert (order.name, order.description, order.req_ids) == ("주문", "주문", ("REQ-01",))
        assert [(a.name, a.is_key) for a in order.attributes] == [("주문번호", True)]

    def test_written_rationale_and_description_are_kept(self, tmp_path: Path) -> None:
        data = _sample()
        data["cases"][0]["relationships"][0]["rationale"] = "주문에 내역이 속한다"
        data["cases"][0]["entities"][0]["description"] = "고객 주문"
        fixtures = load_fixture_set(_write(tmp_path, data))

        state = case_state(fixtures, fixtures.cases[0])

        assert state.relationships[0].rationale == "주문에 내역이 속한다"
        assert state.entities[0].description == "고객 주문"

    def test_functions_are_passed_for_perspectives_that_read_them(self, tmp_path: Path) -> None:
        data = _sample()
        data["cases"][0]["functions"] = [
            {"id": "FUNC-01", "name": "주문 등록", "req_ids": ["REQ-01"]}
        ]
        fixtures = load_fixture_set(_write(tmp_path, data))

        state = case_state(fixtures, fixtures.cases[0])

        [function] = state.functions
        assert (function.id, function.name, function.description) == (
            "FUNC-01",
            "주문 등록",
            "주문 등록",
        )
        assert function.req_ids == ("REQ-01",)


class TestRun:
    def test_reviewer_gets_only_the_case_design_with_the_pack_examples(self) -> None:
        fixtures = load_fixture_set(SAMPLE)
        client, transport = stub_client(*_answers((), (), (), ()))

        run_cases(client, A05, fixtures, SETTINGS)

        assert [r.stage for r in transport.sent] == ["A05"] * 4
        assert len(transport.sent[0].messages) > 2  # 팩 few-shot 예시가 대화 쌍으로 들어간다
        data = json.loads(unwrap_data(transport.sent[1].messages[-1].content))
        assert set(data) == {"requirements", "entities", "relationships"}
        assert [(r["id"], r["cardinality"]) for r in data["relationships"]] == [("REL-01", "1:1")]

    def test_found_missed_and_false_positive_findings_are_counted(self) -> None:
        fixtures = load_fixture_set(SAMPLE)
        client, _ = stub_client(
            *_answers(
                (_finding("REL-01"),),
                (_finding("REL-01"),),
                (_finding("ENT-01", kind="entity"),),
                (),
            )
        )

        summary = summarize(run_cases(client, A05, fixtures, SETTINGS))

        assert (summary.cases, summary.failed_cases) == (4, 0)
        assert (summary.expected_total, summary.expected_found) == (2, 1)
        assert (summary.findings_total, summary.findings_matched) == (3, 1)
        assert summary.normal_false_positives == 1
        assert summary.recall == 0.5
        assert summary.precision == pytest.approx(1 / 3)

    def test_failed_call_is_counted_as_failure_not_as_no_findings(self) -> None:
        fixtures = load_fixture_set(SAMPLE)
        client, _ = stub_client(*_answers(()), refusal(), *_answers((), ()))

        results = run_cases(client, A05, fixtures, SETTINGS)
        summary = summarize(results)

        assert (results[1].ok, results[1].error_code) == (False, "LLM_REFUSED")
        assert summary.failed_cases == 1
        # 실패한 사례(D1)는 지표에서 빼고 D2의 기대 결함 하나만 센다
        assert (summary.expected_total, summary.expected_found) == (1, 0)

    def test_precision_is_none_without_findings(self) -> None:
        fixtures = load_fixture_set(SAMPLE)
        client, _ = stub_client(*_answers((), (), (), ()))

        summary = summarize(run_cases(client, A05, fixtures, SETTINGS))

        assert summary.recall == 0.0
        assert summary.precision is None

    def test_perspective_needing_normalized_input_stops_before_calling(self) -> None:
        fixtures = load_fixture_set(SAMPLE)
        a08_like = Perspective.model_validate(
            {**A05.model_dump(), "inputs": ["entities", "relationships", "normalized"]}
        )
        client, transport = stub_client()

        with pytest.raises(FixtureError, match="normalized"):
            run_cases(client, a08_like, fixtures, SETTINGS)
        assert transport.sent == ()

    def test_reviewer_id_must_match_the_perspective(self) -> None:
        fixtures = load_fixture_set(SAMPLE)
        other = Perspective.model_validate({**A05.model_dump(), "reviewer_id": "A06"})
        client, transport = stub_client()

        with pytest.raises(FixtureError, match="A06"):
            run_cases(client, other, fixtures, SETTINGS)
        assert transport.sent == ()


class TestReport:
    def test_report_lists_found_and_missed_targets_per_case(self) -> None:
        fixtures = load_fixture_set(SAMPLE)
        client, _ = stub_client(*_answers((), (_finding("REL-01"),), (), ()))
        results = run_cases(client, A05, fixtures, SETTINGS)

        report = build_report(fixtures, A05, results)

        assert (report["reviewer_id"], report["set"]) == ("A05", "합성_예시_v1")
        assert report["prompt_version"] == A05.prompt_version
        by_id = {c["case_id"]: c for c in report["cases"]}
        assert (by_id["SAMPLE-01-D1"]["found"], by_id["SAMPLE-01-D1"]["missed"]) == (["REL-01"], [])
        assert (by_id["SAMPLE-01-D2"]["found"], by_id["SAMPLE-01-D2"]["missed"]) == ([], ["REL-01"])
        finding = by_id["SAMPLE-01-D1"]["findings"][0]
        assert finding["targets"] == [{"kind": "relationship", "id": "REL-01"}]
        assert report["summary"]["expected_found"] == 1
        assert report["summary"]["input_tokens"] == 40


class TestMain:
    def test_main_writes_the_report_using_the_perspective_named_in_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client, transport = stub_client(
            *_answers((), (_finding("REL-01"),), (_finding("REL-01"),), ())
        )
        monkeypatch.setattr(eval_fixtures, "openai_client", lambda settings: client)
        out = tmp_path / "report.json"

        code = main([str(SAMPLE), "--out", str(out)], settings=SETTINGS)

        assert code == 0
        assert transport.sent[0].prompt_version == A05.prompt_version
        saved = json.loads(out.read_text(encoding="utf-8"))
        assert saved["summary"]["expected_found"] == 2
        assert "발견율 2/2" in capsys.readouterr().out

    def test_main_reports_a_bad_file_without_a_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("reviewer_id: A05\n", encoding="utf-8")

        code = main([str(bad)], settings=SETTINGS)

        assert code == 2
        assert "bad.yaml" in capsys.readouterr().err

    def test_main_reports_a_missing_api_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main([str(SAMPLE)], settings=SETTINGS)

        assert code == 2
        assert "SPECTON_OPENAI_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize(("kind", "category"), [("NFR", None), ("FR", "security")])
def test_requirement_category_is_rejected_when_loading_the_fixture(
    tmp_path: Path, kind: str, category: str | None
) -> None:
    data = _sample()
    data["cases"][0]["requirements"][0].update(type=kind, nfr_category=category)
    with pytest.raises(FixtureError, match="nfr_category"):
        load_fixture_set(_write(tmp_path, data))


def test_source_labels_are_opaque_in_model_inputs_but_preserved_in_reports() -> None:
    data = _sample()
    data["cases"] = data["cases"][1:2]
    data["cases"][0]["case_id"] = "CASE_HINT_expected_cardinality"
    data["cases"][0]["source_id"] = "ANSWER_HINT_cardinality_defect"
    fixtures = eval_fixtures.FixtureSet.model_validate(data)
    client, transport = stub_client(reply(ReviewOutput(findings=())))
    results = run_cases(client, A05, fixtures, SETTINGS)
    payload = json.loads(unwrap_data(transport.sent[0].messages[-1].content))
    requirement = payload["requirements"][0]
    assert requirement["id"] == "REQ-01"
    assert requirement["text"] == fixtures.cases[0].requirements[0].text
    wire = "\n".join(message.content for message in transport.sent[0].messages)
    assert "ANSWER_HINT_cardinality_defect" not in wire
    assert "CASE_HINT_expected_cardinality" not in wire
    assert requirement["source_id"].startswith("source-")
    assert "expected" not in payload
    report = build_report(fixtures, A05, results)
    assert report["input_version"] == "fixed-review-input-v2"
    assert report["cases"][0]["source_id"] == "ANSWER_HINT_cardinality_defect"
    assert report["cases"][0]["expected"] == [{"target": "REL-01", "defect": "cardinality"}]


def test_cases_of_one_source_keep_tracking_ids_and_share_the_opaque_wire_identity() -> None:
    data = _sample()
    data["cases"] = data["cases"][:2]
    fixtures = eval_fixtures.FixtureSet.model_validate(data)
    original, defect = fixtures.cases
    assert original.source_id == defect.source_id
    client, transport = stub_client(*_answers((), ()))
    run_cases(client, A05, fixtures, SETTINGS)
    ids = [
        json.loads(unwrap_data(request.messages[-1].content))["requirements"][0]["source_id"]
        for request in transport.sent
    ]
    assert ids[0] == ids[1] and ids[0] != original.source_id
    assert case_state(fixtures, original).requirements[0].source_id == original.source_id


def test_report_rejects_mixing_original_and_opaque_source_input_versions() -> None:
    data = _sample()
    data["cases"] = data["cases"][:2]
    fixtures = eval_fixtures.FixtureSet.model_validate(data)
    client, _ = stub_client(*_answers((), ()))
    first, second = run_cases(client, A05, fixtures, SETTINGS)
    old_input = replace(
        second, provenance={k: v for k, v in second.provenance.items() if k != "input_version"}
    )
    with pytest.raises(FixtureError, match="서로 다른"):
        build_report(fixtures, A05, (first, old_input))


def test_normal_runtime_review_keeps_original_source_ids_by_default() -> None:
    from specton.review.reviewer import review_perspective

    fixtures = eval_fixtures.FixtureSet.model_validate(_sample())
    state = case_state(fixtures, fixtures.cases[0])
    client, transport = stub_client(reply(ReviewOutput(findings=())))
    review_perspective(client, A05, state, SETTINGS)
    payload = json.loads(unwrap_data(transport.sent[0].messages[-1].content))
    assert payload["requirements"][0]["source_id"] == fixtures.cases[0].source_id
