import json
from pathlib import Path

import pytest
import yaml

from specton.config import Settings
from specton.contracts import DesignState, Entity, FindingDraft, Function, Requirement
from specton.llm.errors import LLMTimeoutError
from specton.llm.stub import refusal, reply, stub_client
from specton.nodes.common import COMMON_RULES, data_block, unwrap_data
from specton.packs.examples import load_examples
from specton.review.perspective import Perspective
from specton.review.reviewer import (
    CombinedReviewOutput,
    PerspectiveFindings,
    ReviewOutput,
    run_review,
)


def _perspective(reviewer_id: str, *inputs: str) -> Perspective:
    return Perspective.model_validate(
        {
            "reviewer_id": reviewer_id,
            "name": f"{reviewer_id} 관점",
            "prompt_version": f"{reviewer_id.lower()}-v1",
            "instructions": f"{reviewer_id} 기준으로 검토한다",
            "checklist": [f"{reviewer_id} 점검 항목"],
            "inputs": list(inputs) or ["requirements"],
            "false_positive_guards": [f"{reviewer_id} 오탐 기준"],
        }
    )


A05 = _perspective("A05", "requirements", "entities")
A06 = _perspective("A06", "requirements", "functions")


def _state() -> DesignState:
    req = Requirement(
        id="REQ-01",
        source_ref={"kind": "csv", "row": 2},
        text="주문을 취소할 수 있다",
        original_text="주문을 취소할 수 있다",
        type="FR",
        analysis_version=1,
    )
    entity = Entity(
        id="ENT-01",
        pack="inventory",
        name="주문",
        description="고객 주문",
        attributes=[
            {"id": "ATTR-01", "name": "주문번호", "data_type": "integer", "req_ids": ["REQ-01"]}
        ],
        req_ids=["REQ-01"],
    )
    function = Function(id="FUNC-01", name="주문 취소", description="취소", req_ids=["REQ-01"])
    return DesignState(
        run_id="run-1",
        revision=3,
        iteration=1,
        requirements=[req],
        entities=[entity],
        functions=[function],
    )


def _draft(kind: str = "missing_status") -> FindingDraft:
    return FindingDraft(
        kind=kind,
        severity="major",
        targets=[{"kind": "entity", "id": "ENT-01"}],
        evidence=[{"req_id": "REQ-01", "quote": "주문을 취소할 수 있다"}],
        suggestion="취소 상태를 저장하는 속성을 추가한다",
    )


def _settings(mode: str) -> Settings:
    return Settings(_env_file=None, review_mode=mode)


class TestParallel:
    def test_calls_each_perspective_once_and_tags_findings(self) -> None:
        client, transport = stub_client(
            reply(ReviewOutput(findings=(_draft(),))), reply(ReviewOutput(findings=()))
        )

        run = run_review(client, [A05, A06], _state(), _settings("parallel"))

        assert [r.stage for r in transport.sent] == ["A05", "A06"]
        assert [(r.branch, r.ok, len(r.findings)) for r in run.results] == [
            ("A05", True, 1),
            ("A06", True, 0),
        ]
        finding = run.results[0].findings[0]
        assert (finding.reviewer_id, finding.source, finding.iteration) == ("A05", "llm", 1)
        assert run.complete

    def test_failed_perspective_keeps_other_results(self) -> None:
        client, _ = stub_client(refusal(), reply(ReviewOutput(findings=(_draft(),))))

        run = run_review(client, [A05, A06], _state(), _settings("parallel"))

        assert [(r.branch, r.ok, r.error_code) for r in run.results] == [
            ("A05", False, "LLM_REFUSED"),
            ("A06", True, None),
        ]
        assert len(run.results[1].findings) == 1
        assert not run.complete
        assert len(run.calls) == 2

    def test_prompt_uses_only_the_selected_inputs(self) -> None:
        client, transport = stub_client(reply(ReviewOutput(findings=())))

        run_review(client, [A05], _state(), _settings("parallel"))

        system, user = transport.sent[0].messages
        assert "A05 점검 항목" in system.content and "A05 오탐 기준" in system.content
        assert COMMON_RULES in system.content
        data = json.loads(unwrap_data(user.content))
        assert list(data) == ["requirements", "entities"]

    def test_empty_object_is_not_a_valid_answer(self) -> None:
        client, transport = stub_client(reply("{}"), reply(ReviewOutput(findings=())))

        run = run_review(client, [A05], _state(), _settings("parallel"))

        assert len(transport.sent) == 2
        assert run.results[0].ok

    def test_critical_from_the_llm_is_retried(self) -> None:
        critical = _draft().model_dump(mode="json") | {"severity": "critical"}
        bad = json.dumps({"findings": [critical]}, ensure_ascii=False)
        client, transport = stub_client(reply(bad), reply(ReviewOutput(findings=(_draft(),))))

        run = run_review(client, [A05], _state(), _settings("parallel"))

        assert len(transport.sent) == 2
        assert run.results[0].findings[0].severity == "major"
        assert "major·minor" in transport.sent[0].messages[0].content


class TestCombined:
    def test_calls_once_and_splits_findings_by_reviewer(self) -> None:
        output = CombinedReviewOutput(
            perspectives=(
                PerspectiveFindings(reviewer_id="A06", findings=(_draft(),)),
                PerspectiveFindings(reviewer_id="A05", findings=()),
            )
        )
        client, transport = stub_client(reply(output))

        run = run_review(client, [A05, A06], _state(), _settings("combined"))

        assert len(transport.sent) == 1
        assert transport.sent[0].prompt_version == "A05=a05-v1,A06=a06-v1"
        assert [(r.branch, r.ok, len(r.findings)) for r in run.results] == [
            ("A05", True, 0),
            ("A06", True, 1),
        ]

    def test_missing_perspective_is_marked_failed(self) -> None:
        output = CombinedReviewOutput(
            perspectives=(PerspectiveFindings(reviewer_id="A05", findings=()),)
        )
        client, _ = stub_client(reply(output))

        run = run_review(client, [A05, A06], _state(), _settings("combined"))

        assert [(r.branch, r.ok, r.error_code) for r in run.results] == [
            ("A05", True, None),
            ("A06", False, "LLM_OUTPUT_INVALID"),
        ]
        assert not run.complete

    def test_call_failure_fails_every_perspective(self) -> None:
        client, _ = stub_client(LLMTimeoutError("timeout"))

        run = run_review(client, [A05, A06], _state(), _settings("combined"))

        assert [(r.ok, r.error_code) for r in run.results] == [
            (False, "LLM_UNAVAILABLE"),
            (False, "LLM_UNAVAILABLE"),
        ]


class TestFinding:
    @pytest.mark.parametrize("mode", ["parallel", "combined"])
    def test_ids_and_revision_come_from_code(self, mode: str) -> None:
        output = (
            ReviewOutput(findings=(_draft("a"), _draft("b")))
            if mode == "parallel"
            else CombinedReviewOutput(
                perspectives=(
                    PerspectiveFindings(reviewer_id="A05", findings=(_draft("a"), _draft("b"))),
                )
            )
        )
        client, _ = stub_client(reply(output))

        run = run_review(client, [A05], _state(), _settings(mode))

        result = run.results[0]
        assert result.revision == 3
        assert [f.id for f in result.findings] == ["A05-1-1", "A05-1-2"]

    def test_fingerprint_ignores_wording_but_not_targets(self) -> None:
        same = _draft().evolve(suggestion="다른 문장")
        other = _draft().evolve(targets=[{"kind": "entity", "id": "ENT-02"}])
        client, _ = stub_client(reply(ReviewOutput(findings=(_draft(), same, other))))

        run = run_review(client, [A05], _state(), _settings("parallel"))

        prints = [f.fingerprint for f in run.results[0].findings]
        assert prints[0] == prints[1] != prints[2]


def _write_example(root: Path, reviewer_id: str = "A05") -> None:
    """임시 팩에 관점 예시 1건을 쓴다. 입력은 관점의 inputs 모양, 출력은 ReviewOutput 모양."""
    path = root / "domain_packs" / "inventory" / "examples" / f"{reviewer_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    example = {
        "source_id": "INV-005",
        "input": {"requirements": [{"id": "REQ-01", "text": "예시 요구"}], "entities": []},
        "output": ReviewOutput(findings=(_draft("example_kind"),)).model_dump(mode="json"),
    }
    header = {"agent": reviewer_id, "role": "review", "status": "draft", "examples": [example]}
    path.write_text(yaml.safe_dump(header, allow_unicode=True, sort_keys=False), encoding="utf-8")


class TestFewShot:
    def test_parallel_puts_examples_as_conversation_pairs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_example(tmp_path)
        monkeypatch.chdir(tmp_path)
        client, transport = stub_client(reply(ReviewOutput(findings=())))

        run_review(client, [A05], _state(), _settings("parallel"), pack="inventory")

        messages = transport.sent[0].messages
        assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
        assert "example_kind" in messages[2].content

    def test_combined_puts_examples_inside_each_perspective_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_example(tmp_path, "A05")
        _write_example(tmp_path, "A06")
        monkeypatch.chdir(tmp_path)
        output = CombinedReviewOutput(
            perspectives=(
                PerspectiveFindings(reviewer_id="A05", findings=()),
                PerspectiveFindings(reviewer_id="A06", findings=()),
            )
        )
        client, transport = stub_client(reply(output))

        run_review(client, [A05, A06], _state(), _settings("combined"), pack="inventory")

        messages = transport.sent[0].messages
        assert [m.role for m in messages] == ["system", "user"]
        a05_block = messages[0].content.split("## A05")[1].split("## A06")[0]
        assert "예시" in a05_block and "example_kind" in a05_block
        assert (
            data_block({"requirements": [{"id": "REQ-01", "text": "예시 요구"}], "entities": []})
            in a05_block
        )

    def test_without_pack_no_examples_are_loaded(self) -> None:
        client, transport = stub_client(reply(ReviewOutput(findings=())))

        run_review(client, [A05], _state(), _settings("parallel"))

        assert [m.role for m in transport.sent[0].messages] == ["system", "user"]


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
@pytest.mark.parametrize("reviewer_id", ["A05", "A06", "A07", "A08"])
def test_pack_review_examples_match_the_review_output(pack: str, reviewer_id: str) -> None:
    root = Path(__file__).resolve().parents[2] / "domain_packs"

    load_examples(pack, reviewer_id, ReviewOutput, root=root)


@pytest.mark.parametrize("pack", ["inventory", "maintenance"])
@pytest.mark.parametrize("reviewer_id", ["A05", "A06", "A07", "A08"])
def test_pack_review_examples_are_grounded(pack: str, reviewer_id: str) -> None:
    """예시 지적도 근거 확인(merge_review)을 통과해야 한다. 본보기가 버려질 지적이면 안 된다."""
    for example in load_examples(pack, reviewer_id, ReviewOutput):
        assert isinstance(example.input, dict)
        texts = {r["id"]: " ".join(r["text"].split()) for r in example.input["requirements"]}
        known = {
            (kind, item["id"])
            for kind, section in [
                ("requirement", "requirements"),
                ("function", "functions"),
                ("entity", "entities"),
                ("relationship", "relationships"),
            ]
            for item in example.input.get(section, [])
        }
        for finding in example.output.findings:
            assert {(t.kind, t.id) for t in finding.targets} <= known, finding.targets
            for evidence in finding.evidence:
                assert evidence.req_id in texts, evidence.req_id
                assert " ".join(evidence.quote.split()) in texts[evidence.req_id], evidence.quote
