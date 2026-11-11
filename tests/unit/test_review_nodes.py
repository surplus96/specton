"""#17·#18 검토 노드(A05~A08)와 재작업 판단 노드(A09)를 그래프에 잇는다. LLM은 stub이다."""

import json
from collections.abc import Mapping
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from specton.agent_nodes import review_nodes, router_node
from specton.config import Settings
from specton.contracts import DesignState, FindingDraft, Requirement
from specton.contracts.normalized import NormalizedModel
from specton.contracts.requirements import QualityIssue
from specton.contracts.state import VersionInfo
from specton.graph import REVIEWERS, GraphState, Node, build_graph, initial_state
from specton.llm.errors import LLMTimeoutError
from specton.llm.stub import reply, stub_client
from specton.nodes import a09_rework_router
from specton.nodes.a09_rework_router import A09Output
from specton.nodes.common import unwrap_data
from specton.review.perspective import load_perspectives
from specton.review.reviewer import CombinedReviewOutput, PerspectiveFindings, ReviewOutput

PACK = "inventory"
REQ = Requirement(
    id="REQ-01",
    source_ref={"file_format": "csv", "row": 2},
    text="주문을 취소할 수 있다",
    draft_text="주문을 취소할 수 있다",
    type="FR",
    quality_issues=[QualityIssue(kind="ambiguous", message="취소 사유가 없습니다")],
    analysis_version=1,
)


def _settings(mode: str = "parallel") -> Settings:
    return Settings(_env_file=None, review_mode=mode)


# A08은 정리 결과를 입력으로 고른다(#12). 검토 노드만 보는 이 시험에서는 빈 정리 결과로 둔다.
NORMALIZED = NormalizedModel(
    pack=PACK,
    pack_version="test",
    rules_version="test",
    lexicon_digest="test",
    tables=(),
    foreign_keys=(),
)


def _design() -> DesignState:
    return DesignState(
        run_id="run-1",
        requirements=[REQ],
        versions=VersionInfo(pack_id=PACK),
        normalized=NORMALIZED,
    )


def _normalize(state: GraphState) -> Mapping[str, Any]:
    """정리 노드 대신 정리 결과를 다시 채운다. 재작업은 정리 결과를 비운다(graph.py)."""
    return {"design": state["design"].evolve(normalized=NORMALIZED)}


def _draft(stage: str | None = None) -> FindingDraft:
    return FindingDraft.model_validate(
        {
            "kind": "missing_cancel_reason",
            "severity": "major",
            "targets": [{"kind": "requirement", "id": "REQ-01"}],
            "evidence": [{"req_id": "REQ-01", "quote": "주문을 취소할 수 있다"}],
            "suggestion": "취소 사유를 저장한다",
            "target_stage": stage,
        }
    )


def _state(**extra: Any) -> GraphState:
    return GraphState(**{**initial_state(_design()), **extra})  # type: ignore[typeddict-item]


# 검토 노드


def test_parallel_reviewer_node_reviews_its_own_perspective() -> None:
    client, transport = stub_client(
        reply(ReviewOutput(findings=(_draft(),))),
        reply(
            '{"decisions":[{"candidate_id":"A06-0-1","verdict":"missing",'
            '"required_behavior":"등록","checked_design_ids":["REQ-01"],'
            '"remaining_gap":"등록 동작 누락","rationale":"전체 설계 대조"}]}'
        ),
    )
    nodes = review_nodes(lambda: client, _settings())

    update = nodes["A06"](_state())

    result = update["branches"]["A06"]
    assert (result.ok, [f.id for f in result.findings]) == (True, ["A06-0-1"])
    assert [(r.stage, r.model) for r in transport.sent] == [
        ("A06", _settings().review_model),
        ("A06_CONFIRM", _settings().review_model),
    ]
    assert "design" not in update  # 병렬 가지는 design을 쓰지 않는다 (합류에서 버전을 남긴다)


def test_combined_mode_reviews_every_perspective_in_the_first_node() -> None:
    combined = CombinedReviewOutput(
        perspectives=tuple(PerspectiveFindings(reviewer_id=r, findings=()) for r in REVIEWERS)
    )
    client, transport = stub_client(reply(combined))
    nodes = review_nodes(lambda: client, _settings("combined"))

    first = nodes[REVIEWERS[0]](_state())
    others = [nodes[r](_state()) for r in REVIEWERS[1:]]

    assert set(first["branches"]) == set(REVIEWERS)
    assert others == [{}, {}, {}]
    assert len(transport.sent) == 1


def test_reviewer_failure_is_kept_as_a_failed_branch() -> None:
    client, _ = stub_client(LLMTimeoutError("시간 초과"))
    nodes = review_nodes(lambda: client, _settings())

    result = nodes["A05"](_state())["branches"]["A05"]

    assert (result.ok, result.error_code) == (False, "LLM_UNAVAILABLE")  # 실행은 실패시키지 않는다


def test_perspective_files_must_match_the_review_branches() -> None:
    with pytest.raises(ValueError, match="A08"):
        review_nodes(lambda: stub_client()[0], _settings(), load_perspectives()[:3])


# 재작업 판단 노드


def _router_request(update_state: GraphState, answer: A09Output) -> tuple[Any, dict[str, Any]]:
    client, transport = stub_client(reply(answer))
    update = router_node(lambda: client, _settings())(update_state)
    data = json.loads(unwrap_data(transport.sent[0].messages[-1].content)) if transport.sent else {}
    return update, data


def test_router_gets_the_unrouted_findings_of_the_automatic_rework() -> None:
    from specton.review.reviewer import _to_finding

    finding = _to_finding(_draft(), "A06", 0, 1)
    answer = A09Output(decision="functions", rationale="기능에 취소 사유가 없다")

    update, data = _router_request(_state(unrouted=(finding,)), answer)

    assert update["router_stage"] == "functions"
    assert [f["id"] for f in data["findings"]] == ["A06-0-1"]
    assert "feedback" not in data
    versions = update["design"].versions
    assert versions.prompt_versions["A09"] == a09_rework_router.PROMPT_VERSION


def test_router_gets_the_feedback_of_a_final_review_revision() -> None:
    revise = {"kind": "review", "decision": "revise", "feedback": "취소 사유가 빠졌다"}
    answer = A09Output(decision="requirements", rationale="요구사항부터 고친다")

    update, data = _router_request(_state(revising=True, review_response=revise), answer)

    assert update["router_stage"] == "requirements"
    assert (data["feedback"], data["findings"]) == ("취소 사유가 빠졌다", [])


def test_revision_without_feedback_asks_a_person_without_calling_the_router() -> None:
    revise = {"kind": "review", "decision": "revise", "feedback": ""}

    update, data = _router_request(
        _state(revising=True, review_response=revise),
        A09Output(decision="functions", rationale="x"),
    )

    assert (update["router_stage"], data) == (None, {})


# 그래프


def test_unrouted_finding_goes_through_the_router_to_rework_and_records_versions() -> None:
    """A06 지적에 단계가 없으면 A09가 정한 단계로 재작업한다. 두 번째 검토는 지적이 없다."""
    from specton.llm.client import LLMClient

    class Transport:
        a06_count = 0

        def send(self, request, output_model):
            if request.stage == "A06_CONFIRM":
                return reply(
                    json.dumps(
                        {
                            "decisions": [
                                {
                                    "candidate_id": "A06-0-1",
                                    "verdict": "missing",
                                    "required_behavior": "취소 사유 기록",
                                    "checked_design_ids": ["REQ-01"],
                                    "remaining_gap": "사유 누락",
                                    "rationale": "기능 설계 대조",
                                }
                            ]
                        }
                    )
                )
            if request.stage == "A09":
                return reply(A09Output(decision="functions", rationale="기능에 취소 사유가 없다"))
            if request.stage == "A06":
                self.a06_count += 1
                if self.a06_count == 1:
                    return reply(ReviewOutput(findings=(_draft(),)))
            return reply(ReviewOutput(findings=()))

    client = LLMClient(Transport(), max_structured_retries=2)
    visited: list[str] = []

    def a02(state: GraphState) -> Mapping[str, Any]:
        visited.append("a02")
        return {}

    nodes: dict[str, Node] = {
        **review_nodes(lambda: client, _settings()),
        "a09": router_node(lambda: client, _settings()),
        "a02": a02,
        "normalize": _normalize,
    }
    graph = build_graph(nodes, checkpointer=InMemorySaver(), max_rework=3)
    config = {"configurable": {"thread_id": "run-1"}}
    graph.invoke(initial_state(_design()), config)

    review = graph.invoke(Command(resume={"kind": "requirements", "answers": []}), config)

    assert review["__interrupt__"][0].value["kind"] == "review"
    assert visited == ["a02", "a02"]  # A09가 정한 기능 단계로 한 번 재작업
    design: DesignState = review["design"]
    assert design.revision == 1
    assert set(REVIEWERS) | {"A09"} <= set(design.versions.prompt_versions)
    assert design.versions.model_names["A05"] == _settings().review_model


@pytest.mark.parametrize(
    "answer",
    [
        a09_rework_router.RouterAnswer(stage=None, rationale="근거가 부족합니다"),
        a09_rework_router.RouterAnswer(stage=None, error_code="LLM_TIMEOUT"),
        a09_rework_router.RouterAnswer(
            stage=a09_rework_router.TargetStage.FUNCTIONS, rationale="기능 책임 누락"
        ),
    ],
)
def test_router_diagnostics_are_checkpointed_and_available_in_progress(answer) -> None:
    from unittest.mock import patch

    from specton.node_progress import node_result
    from specton.nodes.common import NodeRun

    state = initial_state(_design())
    state.update(revising=True, review_response={"feedback": "수정해주세요"})
    with patch(
        "specton.agent_nodes.a09_rework_router.run", return_value=NodeRun(output=answer, calls=())
    ):
        update = router_node(lambda: None, _settings())(state)
    record = update["router_decision"]
    assert record == {
        "revision": state["design"].revision,
        "stage": answer.stage.value if answer.stage else None,
        "rationale": answer.rationale,
        "error_code": answer.error_code,
    }
    assert node_result("a09", update)["router_decision"] == record
    state["review_response"] = {"feedback": ""}
    assert router_node(lambda: None, _settings())(state)["router_decision"] is None
