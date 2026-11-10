"""#18: 같은 고정 설계를 실제 그래프 검토 가지로 실행한다. 정답은 받지 않는다.

설계·생성·재작업을 제외한 진단 도구다. 결과의 의미 채점은 실행 뒤 별도로 검토한다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from langgraph.graph import END, START, StateGraph

from specton.agent_nodes import review_nodes
from specton.config import Settings
from specton.contracts import DesignState
from specton.graph import REVIEWERS, GraphState, Node, initial_state
from specton.llm.client import LLMClient
from specton.llm.types import CallRecord
from specton.review.eval_normalization import prepare_normalized, state_provenance
from specton.review.merge import ReviewMerge, merge_review


@dataclass(frozen=True)
class ComparisonRun:
    mode: str
    wall_time_ms: int
    merge: ReviewMerge
    calls: tuple[CallRecord, ...]
    branch_times: dict[str, dict[str, int]]
    provenance: dict[str, str]

    def report(self) -> dict[str, Any]:
        """지적에는 인용이 있으므로 비공개 입력의 결과는 비공개 경로에만 저장한다."""
        return {
            "mode": self.mode,
            "complete": self.merge.complete,
            "wall_time_ms": self.wall_time_ms,
            "branch_times": self.branch_times,
            "failed_branches": list(self.merge.failed_branches),
            "findings": [f.model_dump(mode="json") for f in self.merge.findings],
            "rejected": [
                {"finding_id": r.finding.id, "reason": r.reason} for r in self.merge.rejected
            ],
            "calls": [c.model_dump(mode="json") for c in self.calls],
            "input_tokens": sum(c.input_tokens for c in self.calls),
            "output_tokens": sum(c.output_tokens for c in self.calls),
            "structured_retries": sum(c.attempt > 1 for c in self.calls),
            "sdk_retry_count": None,
            "provenance": self.provenance,
            "scoring": "unscored; target and semantic matching must be reviewed separately",
        }


def run_comparison_condition(
    get_client: Callable[[], LLMClient], settings: Settings, design: DesignState
) -> ComparisonRun:
    """운영과 같은 4개 가지·reducer로 병렬 합류한다. 조건마다 초기 상태를 독립시킨다."""
    prepared = prepare_normalized(design, root=settings.pack_root)
    nodes = review_nodes(get_client, settings)
    times: dict[str, dict[str, int]] = {}
    started = perf_counter()
    graph = StateGraph(GraphState)
    for name in REVIEWERS:
        graph.add_node(name, _timed(nodes[name], name, times, started))  # type: ignore[call-overload]
        graph.add_edge(START, name)
    graph.add_node("joined", lambda state: {})
    graph.add_edge(list(REVIEWERS), "joined")
    graph.add_edge("joined", END)
    result = graph.compile().invoke(
        initial_state(prepared), config={"max_concurrency": settings.llm_concurrency}
    )
    merged = merge_review(prepared, tuple(result["branches"].values()), REVIEWERS)
    calls = tuple(
        CallRecord.model_validate(c)
        for stage in sorted(result.get("call_summaries", {}))
        for c in result["call_summaries"][stage]
    )
    return ComparisonRun(
        mode=settings.review_mode,
        wall_time_ms=int((perf_counter() - started) * 1000),
        merge=merged,
        calls=calls,
        branch_times=times,
        provenance=state_provenance(prepared),
    )


def _timed(node: Node, name: str, times: dict[str, dict[str, int]], started: float) -> Node:
    def run(state: GraphState) -> dict[str, Any]:
        begin = int((perf_counter() - started) * 1000)
        try:
            return dict(node(state))
        finally:
            times[name] = {
                "start_ms": begin,
                "end_ms": int((perf_counter() - started) * 1000),
            }

    return run
