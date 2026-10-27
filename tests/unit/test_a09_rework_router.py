"""TC-A09: A09 조건부 재작업 판단 노드."""

import json

from specton.config import Settings
from specton.contracts import DesignState, Finding, Requirement
from specton.llm.client import LLMClient
from specton.llm.errors import LLMTimeoutError
from specton.llm.stub import refusal, reply, stub_client
from specton.nodes.a09_rework_router import A09Output, RouterAnswer, run
from specton.nodes.common import NodeRun, unwrap_data
from specton.review.rework import ReworkAction, decide_rework, resolve_with_router


def _requirement(req_id: str, text: str) -> Requirement:
    return Requirement(
        id=req_id,
        source_ref={"kind": "csv", "row": 2},
        text=text,
        original_text=text,
        type="FR",
        analysis_version=1,
    )


STATE = DesignState(
    run_id="run-1",
    requirements=[
        _requirement("REQ-01", "주문을 취소할 수 있다"),
        _requirement("REQ-02", "입고 수량을 기록한다"),
    ],
)


def _unrouted() -> Finding:
    return Finding(
        id="A06-0-1",
        source="llm",
        reviewer_id="A06",
        kind="missing_cancel_reason",
        severity="major",
        targets=[{"kind": "requirement", "id": "REQ-01"}],
        evidence=[{"req_id": "REQ-01", "quote": "주문을 취소할 수 있다"}],
        suggestion="취소 사유를 어디에 남길지 정한다",
        fingerprint="fp-1",
        iteration=0,
    )


def _settings() -> Settings:
    return Settings(_env_file=None)


def _run(client: LLMClient) -> NodeRun[RouterAnswer]:
    return run(client, STATE, _settings(), pack="inventory", findings=[_unrouted()])


def test_returns_the_stage_and_sends_only_related_requirements() -> None:
    client, transport = stub_client(
        reply(A09Output(decision="functions", rationale="기능에 취소 사유 입력이 없다"))
    )

    answer = _run(client).output

    assert (answer.stage, answer.error_code) == ("functions", None)
    request = transport.sent[0]
    assert (request.stage, request.model) == ("A09", _settings().review_model)
    data = json.loads(unwrap_data(request.messages[-1].content))
    assert [r["id"] for r in data["requirements"]] == ["REQ-01"]
    assert [f["id"] for f in data["findings"]] == ["A06-0-1"]


def test_undecidable_answer_has_no_stage() -> None:
    client, _ = stub_client(reply(A09Output(decision="undecidable", rationale="근거 부족")))

    answer = _run(client).output

    assert (answer.stage, answer.rationale, answer.error_code) == (None, "근거 부족", None)


def test_invalid_output_is_retried() -> None:
    client, transport = stub_client(
        reply("{}"), reply(A09Output(decision="data_model", rationale="속성 누락"))
    )

    answer = _run(client).output

    assert answer.stage == "data_model"
    assert len(transport.sent) == 2


def test_disallowed_stage_ends_as_no_answer() -> None:
    bad = json.dumps({"decision": "relationships", "rationale": "관계 문제"})
    client, _ = stub_client(reply(bad), reply(bad), reply(bad))

    node_run = _run(client)

    assert (node_run.output.stage, node_run.output.error_code) == (None, "LLM_OUTPUT_INVALID")
    assert len(node_run.calls) == 3


def test_llm_failure_ends_as_no_answer() -> None:
    for step, code in ((refusal(), "LLM_REFUSED"), (LLMTimeoutError("t"), "LLM_UNAVAILABLE")):
        client, _ = stub_client(step)

        answer = _run(client).output

        assert (answer.stage, answer.error_code) == (None, code)


def test_router_answer_completes_the_rework_decision() -> None:
    decision = decide_rework(
        [_unrouted()], rework_count=0, max_rework=3, previous_fingerprints=frozenset()
    )
    client, transport = stub_client(reply(A09Output(decision="functions", rationale="r")))

    answer = run(client, STATE, _settings(), pack="inventory", findings=decision.unrouted).output
    resolved = resolve_with_router(decision, answer.stage)

    assert (resolved.action, resolved.target_stage) == (ReworkAction.REWORK, "functions")
    assert len(transport.sent) == 1
