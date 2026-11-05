"""#17 실행 한 번의 토큰 한도(`max_tokens_per_run`)와 재분석 버전. LLM은 stub이다.

- 노드는 쓴 토큰을 `tokens_used`에 더하고, 남은 예산을 호출에 넘긴다 (ADR-0012 한도).
- 예산을 다 쓴 뒤에는 LLM을 부르지 않고 `BUDGET_EXCEEDED`로 실행을 끝낸다.
- 요구사항 단계로 다시 분석하면 A01 `analysis_version`이 오른다.
"""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from specton.agent_nodes import design_nodes, review_nodes, router_node
from specton.config import Settings
from specton.contracts import DesignState
from specton.contracts.requirements import SourceRequirement
from specton.contracts.state import VersionInfo
from specton.graph import GraphState, build_graph, initial_state
from specton.llm.client import LLMClient
from specton.llm.errors import LLMBudgetExceededError
from specton.llm.stub import reply, stub_client
from specton.nodes.a01_requirements import A01Output
from specton.review.reviewer import ReviewOutput

PACK = "inventory"
BLOCK = SourceRequirement(
    document_id="doc-1",
    block_id="csv:2",
    source_ref={"file_format": "csv", "row": 2},
    source_text="입고를 등록한다",
    extraction_status="pass",
)
A01_REPLY = A01Output.model_validate(
    {"requirements": [{"source_block_ids": ["csv:2"], "text": "입고를 등록한다", "type": "FR"}]}
)


def _settings(budget: int = 400_000) -> Settings:
    return Settings(_env_file=None, max_tokens_per_run=budget, review_mode="parallel")


def _state(**extra: Any) -> GraphState:
    design = DesignState(
        run_id="run-1", source_requirements=(BLOCK,), versions=VersionInfo(pack_id=PACK)
    )
    return GraphState(**{**initial_state(design), **extra})  # type: ignore[typeddict-item]


def _a01(client: LLMClient, budget: int = 400_000) -> Any:
    return design_nodes(lambda: client, _settings(budget))["a01"]


def test_node_adds_the_tokens_it_used() -> None:
    client, _ = stub_client(reply(A01_REPLY, input_tokens=100, output_tokens=50))

    update = _a01(client)(_state())

    assert update["tokens_used"] == 150


def test_node_does_not_call_the_model_after_the_budget_is_spent() -> None:
    client, transport = stub_client(reply(A01_REPLY))

    with pytest.raises(LLMBudgetExceededError):
        _a01(client, budget=1_000)(_state(tokens_used=1_000))

    assert transport.sent == ()


def test_node_passes_only_the_remaining_budget_to_the_model_call() -> None:
    """남은 예산이 15인데 첫 응답이 20 토큰을 쓰고 형식이 틀리면 재요청하지 않는다."""
    client, transport = stub_client(reply("{}"), reply(A01_REPLY))

    with pytest.raises(LLMBudgetExceededError):
        _a01(client, budget=1_000)(_state(tokens_used=985))

    assert len(transport.sent) == 1


def test_reviewer_and_router_nodes_also_count_their_tokens() -> None:
    client, _ = stub_client(reply(ReviewOutput(findings=()), input_tokens=30, output_tokens=5))

    update = review_nodes(lambda: client, _settings())["A05"](_state())

    assert update["tokens_used"] == 35
    revise = {"kind": "review", "decision": "revise", "feedback": ""}
    assert "tokens_used" not in router_node(lambda: client, _settings())(
        _state(revising=True, review_response=revise)
    )  # 부르지 않았으면 쓴 토큰도 없다


def test_tokens_add_up_across_the_graph() -> None:
    client, _ = stub_client(reply(A01_REPLY, input_tokens=7, output_tokens=3))
    graph = build_graph(design_nodes(lambda: client, _settings()), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "run-1"}}

    graph.invoke(_state(), config, interrupt_after=["a01"])
    state = graph.get_state(config).values

    assert state["tokens_used"] == 10


def test_reanalysis_raises_the_analysis_version() -> None:
    client, _ = stub_client(reply(A01_REPLY), reply(A01_REPLY))
    node = _a01(client)

    first = node(_state())["design"]
    again = node(_state(design=first))["design"]

    assert [r.analysis_version for r in first.requirements] == [1]
    assert [r.analysis_version for r in again.requirements] == [2]
